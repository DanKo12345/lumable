from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal

from app.ambient_color import shape_color
from app.color_stream import ColorStreamEngine
from app.live_sync_metrics import LiveSyncMetrics, LiveSyncReport
from app.screen_profiles import get_profile, resolve_configs
from app.screen_sample import extract_color, sample_step_for
from app.screen_temporal import TemporalFilter


@dataclass(frozen=True)
class AmbientOptions:
    """Immutable capture options. The UI thread swaps a whole new instance; the
    capture thread reads it each frame and re-resolves configs when it changes,
    so nothing mutates shared filter state across threads."""

    monitor_index: int = 0
    region: str = "full"  # full | center | bottom | top
    profile_id: str = "desktop"
    intensity: int = 55    # user boost on top of the profile (55 = neutral)
    smoothness: int = 65   # user smoothing on top of the profile (65 = neutral)
    interval_s: float = 0.05  # min gap between capture attempts; real dt is measured


class _CaptureError(Exception):
    """The screen itself could not be read.

    Only ``mss`` construction and ``grab`` raise this. Everything after the pixels
    arrive is ours, and is reported as a processing error instead.
    """


def _region_for(monitor: dict, region: str) -> dict:
    left = int(monitor["left"])
    top = int(monitor["top"])
    width = int(monitor["width"])
    height = int(monitor["height"])
    if region == "center":
        return {
            "left": left + width // 4,
            "top": top + height // 4,
            "width": max(1, width // 2),
            "height": max(1, height // 2),
        }
    if region == "bottom":
        return {"left": left, "top": top + (height * 2) // 3, "width": width, "height": max(1, height // 3)}
    if region == "top":
        return {"left": left, "top": top, "width": width, "height": max(1, height // 3)}
    return {"left": left, "top": top, "width": width, "height": height}


class AmbientController(QObject):
    """Drives ambient screen-sync: captures the screen on a background thread and
    streams the averaged colour to a sink (BLE write) through ``ColorStreamEngine``.

    The capture thread emits :attr:`color_sampled`; that signal is connected (on the
    main thread) to the engine and can also drive a live UI preview. Capture errors
    surface via :attr:`failed`.
    """

    # final colour → engine/BLE, carrying the session token and frame id that
    # produced it so a drop can be attributed to the right frame of the right run
    color_sampled = Signal(int, int, int, int, int)
    preview_sampled = Signal(int, int, int, int, int, int)      # raw rgb, final rgb → UI preview
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # ~10 sends/sec is the sweet spot for these BLE controllers; the engine
        # coalesces and the BLE layer drops frames when busy, so the link never
        # backs up.
        self._engine = ColorStreamEngine(self, send_interval_ms=100)
        self._options = AmbientOptions()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._metrics = LiveSyncMetrics()
        self._token = 0
        self.color_sampled.connect(self._accept_sample)
        self._engine.frame_coalesced.connect(self._on_frame_coalesced)

    def options(self) -> AmbientOptions:
        return self._options

    def configure(self, **changes) -> None:
        # Just swap the immutable options — the capture thread notices and
        # re-resolves. The engine stays in passthrough; the TemporalFilter is the
        # only smoother for ambient.
        self._options = replace(self._options, **changes)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, sink: Callable[[int, int, int], None], initial: tuple[int, int, int] = (0, 0, 0)) -> None:
        if self.is_running():
            return
        # Passthrough: with easing off, the engine follows the target instantly
        # and only enforces the BLE send-rate cap, so the colour is never
        # smoothed twice (the TemporalFilter owns easing). Seed it with the
        # strip's current colour so no black frame is sent before the first
        # captured one.
        self._engine.set_smoothing(1.0)
        self._engine.start(sink, initial=initial)
        self._stop.clear()
        # Opened before the thread exists, so the very first frame already has a
        # session to belong to.
        self._token = self._metrics.start(time.monotonic())
        thread = threading.Thread(
            target=self._run, args=(initial, self._token), name="AmbientCapture", daemon=True
        )
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._engine.stop()
        # Closed last, after the capture thread has been asked to stop and given
        # time to. The join has a timeout and so guarantees nothing; what makes a
        # straggling frame harmless is the token check in _accept_sample, not the
        # order here.
        self._metrics.stop(time.monotonic())
        self._token = 0

    def live_sync_report(self) -> LiveSyncReport:
        """The current session's numbers, or the last finished one's."""
        return self._metrics.report(time.monotonic())

    def _accept_sample(self, r: int, g: int, b: int, token: int, frame_id: int) -> None:
        """The gate between the capture thread and the strip.

        A queued signal emitted just before a stop can be delivered after the
        next run has begun. Without this check that stale colour would replace
        the current one and be written to the strip — the token would keep the
        numbers honest while the light showed the wrong thing.
        """
        if not token or token != self._token:
            return
        self._engine.set_target(r, g, b, token, frame_id)

    def _on_frame_coalesced(self, token: int, frame_id: int) -> None:
        self._metrics.frame_coalesced(token, frame_id)

    def stream_error_count(self) -> int:
        return self._engine.error_count()

    def last_stream_error(self) -> str:
        return self._engine.last_error()

    def _run(self, initial: tuple[int, int, int], token: int) -> None:
        try:
            import mss
        except Exception as exc:
            self._metrics.capture_failed(token, time.monotonic())
            self.failed.emit(f"screen_capture_unavailable: {exc}")
            return
        try:
            # The temporal filter lives on the capture thread and is seeded with
            # the strip's current colour, so the very first frame is rate-limited
            # too. Its config is updated in place (keeping .last) when the profile
            # or a slider changes — never reset — so switching profile eases from
            # the current colour instead of snapping to black.
            temporal = TemporalFilter(initial=initial)
            applied: AmbientOptions | None = None
            resolved = None
            prev_t = time.monotonic()
            try:
                session = mss.mss()
            except Exception as exc:
                raise _CaptureError(str(exc)) from exc
            with session as sct:
                monitors = sct.monitors
                while not self._stop.is_set():
                    options = self._options
                    if options is not applied:
                        resolved = resolve_configs(
                            get_profile(options.profile_id), options.intensity, options.smoothness
                        )
                        temporal.set_config(resolved.temporal)
                        applied = options

                    index = max(0, options.monitor_index)
                    # monitors[0] is the full virtual desktop; 1.. are physical screens.
                    monitor = monitors[index + 1] if index + 1 < len(monitors) else monitors[-1]
                    frame_started = time.monotonic()
                    try:
                        shot = sct.grab(_region_for(monitor, options.region))
                    except Exception as exc:
                        raise _CaptureError(str(exc)) from exc

                    now = time.monotonic()
                    self._metrics.frame_captured(token, now)
                    dt = now - prev_t
                    prev_t = now

                    # ~2500 samples on a 2-D grid regardless of resolution: a full
                    # pass in pure Python holds the GIL and stalls the UI thread.
                    sample = replace(resolved.sample, sample_step=sample_step_for(shot.width, shot.height))
                    raw = extract_color(shot.bgra, shot.width, shot.height, sample)
                    shaped = shape_color(
                        raw,
                        saturation=resolved.shape.saturation,
                        gamma=resolved.shape.gamma,
                        min_brightness=resolved.shape.min_brightness,
                        max_brightness=resolved.shape.max_brightness,
                        min_saturation=resolved.shape.min_saturation,
                    )
                    final = temporal.push(shaped, dt)
                    # Grab and colour work only: the wait between frames and
                    # everything BLE stay out, or a slow strip would read as slow
                    # code and the worst-frame figure would point at the wrong end.
                    done = time.monotonic()
                    frame_id = self._metrics.frame_processed(
                        token, done, frame_ms=(done - frame_started) * 1000.0
                    )
                    # Only the final colour reaches BLE; the preview shows both.
                    self.preview_sampled.emit(raw[0], raw[1], raw[2], final[0], final[1], final[2])
                    self.color_sampled.emit(final[0], final[1], final[2], token, frame_id)
                    self._stop.wait(max(0.02, options.interval_s))
        except _CaptureError as exc:  # the screen refused to be read
            self._metrics.capture_failed(token, time.monotonic())
            self.failed.emit(str(exc))
        except Exception as exc:  # our own colour code raised
            # Not charged to capture: a bug in the filter or the colour maths
            # reported as "screen capture failed" sends everyone looking at
            # drivers and permissions instead of at this application.
            self._metrics.processing_failed(token, time.monotonic())
            self.failed.emit(str(exc))

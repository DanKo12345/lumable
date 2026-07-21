from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal

from app.ambient_color import shape_color
from app.color_stream import ColorStreamEngine
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

    color_sampled = Signal(int, int, int)                       # final colour → engine/BLE
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
        self.color_sampled.connect(self._engine.set_target)

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
        thread = threading.Thread(
            target=self._run, args=(initial,), name="AmbientCapture", daemon=True
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

    def stream_error_count(self) -> int:
        return self._engine.error_count()

    def last_stream_error(self) -> str:
        return self._engine.last_error()

    def _run(self, initial: tuple[int, int, int]) -> None:
        try:
            import mss
        except Exception as exc:
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
            with mss.mss() as sct:
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
                    shot = sct.grab(_region_for(monitor, options.region))

                    now = time.monotonic()
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
                    # Only the final colour reaches BLE; the preview shows both.
                    self.preview_sampled.emit(raw[0], raw[1], raw[2], final[0], final[1], final[2])
                    self.color_sampled.emit(final[0], final[1], final[2])
                    self._stop.wait(max(0.02, options.interval_s))
        except Exception as exc:  # capture/driver failure — report and stop cleanly.
            self.failed.emit(str(exc))

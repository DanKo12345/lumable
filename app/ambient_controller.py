from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal

from app.ambient_color import average_color, shape_color
from app.color_stream import ColorStreamEngine


@dataclass(frozen=True)
class AmbientOptions:
    monitor_index: int = 0
    region: str = "full"  # full | center | bottom | top
    saturation: float = 1.45
    gamma: float = 1.1
    min_brightness: int = 0
    max_brightness: int = 255
    smoothing: float = 0.35
    sample_step: int = 6
    interval_s: float = 0.08  # ~12 captures/sec


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

    color_sampled = Signal(int, int, int)
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
        self._options = replace(self._options, **changes)
        if "smoothing" in changes:
            self._engine.set_smoothing(self._options.smoothing)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, sink: Callable[[int, int, int], None]) -> None:
        if self.is_running():
            return
        self._engine.set_smoothing(self._options.smoothing)
        self._engine.start(sink, initial=(0, 0, 0))
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="AmbientCapture", daemon=True)
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

    def _run(self) -> None:
        try:
            import mss
        except Exception as exc:
            self.failed.emit(f"screen_capture_unavailable: {exc}")
            return
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                while not self._stop.is_set():
                    options = self._options
                    index = max(0, options.monitor_index)
                    # monitors[0] is the full virtual desktop; 1.. are physical screens.
                    monitor = monitors[index + 1] if index + 1 < len(monitors) else monitors[-1]
                    shot = sct.grab(_region_for(monitor, options.region))
                    # Sample only ~2500 pixels regardless of resolution: averaging
                    # millions of pixels in pure Python holds the GIL and stalls
                    # the UI thread. Pass the raw buffer (no full-size copy).
                    pixel_count = max(1, shot.width * shot.height)
                    step = max(options.sample_step, pixel_count // 2500)
                    color = average_color(shot.bgra, channels=4, sample_step=step)
                    shaped = shape_color(
                        color,
                        saturation=options.saturation,
                        gamma=options.gamma,
                        min_brightness=options.min_brightness,
                        max_brightness=options.max_brightness,
                    )
                    self.color_sampled.emit(shaped[0], shaped[1], shaped[2])
                    self._stop.wait(max(0.02, options.interval_s))
        except Exception as exc:  # capture/driver failure — report and stop cleanly.
            self.failed.emit(str(exc))

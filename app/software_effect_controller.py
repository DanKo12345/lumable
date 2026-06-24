from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal

from app.color_stream import ColorStreamEngine
from app.software_effects import RGB, render

_BaseProvider = Callable[[], RGB]


class SoftwareEffectController(QObject):
    """Runs an app-driven animation (breathing/rainbow/candle/gradient) and streams
    the colour to a sink (BLE write) through :class:`ColorStreamEngine`.

    Unlike ambient/music there's no capture to do, so the animation is advanced on
    a lightweight UI-thread timer rather than a background thread. The engine still
    throttles the BLE send-rate and eases transitions.
    """

    color_changed = Signal(int, int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = ColorStreamEngine(self, send_interval_ms=70)
        self._effect = "breathing"
        self._speed = 0.3  # animation cycles per second
        self._phase = 0.0
        self._base_provider: _BaseProvider | None = None
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(33)  # ~30 fps target generation
        self._timer.timeout.connect(self._tick)

    def configure(self, *, effect: str | None = None, speed: float | None = None) -> None:
        if effect is not None:
            self._effect = effect
        if speed is not None:
            self._speed = max(0.0, float(speed))

    def effect(self) -> str:
        return self._effect

    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, sink: Callable[[int, int, int], None], base_provider: _BaseProvider) -> None:
        if self.is_running():
            return
        self._base_provider = base_provider
        self._phase = 0.0
        # A little easing smooths the BLE-rate steps without lagging the animation.
        self._engine.set_smoothing(0.6)
        self._engine.start(sink, initial=(0, 0, 0))
        self._elapsed.restart()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._engine.stop()

    def stream_error_count(self) -> int:
        return self._engine.error_count()

    def last_stream_error(self) -> str:
        return self._engine.last_error()

    def _tick(self) -> None:
        elapsed_ms = self._elapsed.restart()
        # Advance the animation phase in real time (cycles loop at 1.0).
        self._phase = (self._phase + (elapsed_ms / 1000.0) * self._speed) % 1.0
        base = self._base_provider() if self._base_provider is not None else (255, 255, 255)
        red, green, blue = render(self._effect, self._phase, base)
        self._engine.set_target(red, green, blue)
        self.color_changed.emit(red, green, blue)

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal

from app.color_stream import ColorStreamEngine
from app.diy_effects import DiyEffect, color_at, duration_scale


class DiyEffectController(QObject):
    """Streams a user-built ("DIY") colour-stop animation to a sink (BLE write)
    through :class:`ColorStreamEngine`, so it runs on any controller regardless of
    its firmware effects. The pure timeline maths live in app.diy_effects; this is
    just the timer + engine glue (mirrors SoftwareEffectController)."""

    color_changed = Signal(int, int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = ColorStreamEngine(self, send_interval_ms=70)
        self._effect: DiyEffect | None = None
        self._wall_ms = 0.0  # accumulated wall-clock since start
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(33)  # ~30 fps generation
        self._timer.timeout.connect(self._tick)

    def configure(self, effect: DiyEffect) -> None:
        self._effect = effect

    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, sink: Callable[[int, int, int], None]) -> None:
        if self.is_running() or self._effect is None:
            return
        self._wall_ms = 0.0
        # Light easing smooths the 70ms BLE steps; the DIY fades stay crisp enough.
        self._engine.set_smoothing(0.4)
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
        effect = self._effect
        if effect is None or not effect.steps:
            return
        self._wall_ms += self._elapsed.restart()
        scale = duration_scale(effect.speed)
        raw_t = self._wall_ms / scale if scale > 0 else self._wall_ms
        red, green, blue = color_at(effect, raw_t)
        self._engine.set_target(red, green, blue)
        self.color_changed.emit(red, green, blue)

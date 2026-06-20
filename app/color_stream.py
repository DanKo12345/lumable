from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer

RGB = tuple[int, int, int]


def _clamp8(value: float) -> int:
    return max(0, min(255, round(value)))


class ColorSmoother:
    """Eases a current colour toward a target, one step per call.

    Pure (no Qt) so the easing behaviour can be unit-tested. ``smoothing`` is the
    fraction of the remaining distance covered per ``advance()`` (0..1): higher is
    snappier, lower is calmer. Used to keep app-streamed effects from flickering.
    """

    def __init__(self, smoothing: float = 0.35) -> None:
        self._smoothing = max(0.01, min(1.0, float(smoothing)))
        self._cur = [0.0, 0.0, 0.0]
        self._target = [0.0, 0.0, 0.0]

    def set_smoothing(self, smoothing: float) -> None:
        self._smoothing = max(0.01, min(1.0, float(smoothing)))

    def reset(self, rgb: RGB) -> None:
        self._cur = [float(_clamp8(c)) for c in rgb]
        self._target = list(self._cur)

    def set_target(self, rgb: RGB) -> None:
        self._target = [float(_clamp8(c)) for c in rgb]

    def advance(self) -> RGB:
        for i in range(3):
            self._cur[i] += (self._target[i] - self._cur[i]) * self._smoothing
        return (_clamp8(self._cur[0]), _clamp8(self._cur[1]), _clamp8(self._cur[2]))

    def at_target(self, tolerance: int = 1) -> bool:
        return all(abs(self._cur[i] - self._target[i]) <= tolerance for i in range(3))


class ColorStreamEngine(QObject):
    """Streams a smoothly-eased colour to a sink (e.g. a BLE write) at a capped
    rate. This is the foundation for app-driven effects — ambient screen sync,
    music reactivity, custom effects — that the cheap controllers can't do in
    firmware.

    The engine ticks fast for smooth interpolation but only calls the sink at
    ``send_interval_ms`` and only when the colour actually changed, so the BLE
    link (which handles ~10-20 writes/sec) is never flooded.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        tick_ms: int = 33,
        send_interval_ms: int = 70,
        smoothing: float = 0.35,
    ) -> None:
        super().__init__(parent)
        self._smoother = ColorSmoother(smoothing)
        self._send_interval_ms = max(33, int(send_interval_ms))
        self._sink: Callable[[int, int, int], None] | None = None
        self._last_sent: RGB | None = None
        self._last_send_ms = 0
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(max(16, int(tick_ms)))
        self._timer.timeout.connect(self._tick)

    def set_smoothing(self, smoothing: float) -> None:
        self._smoother.set_smoothing(smoothing)

    def set_send_interval_ms(self, interval_ms: int) -> None:
        self._send_interval_ms = max(33, int(interval_ms))

    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, sink: Callable[[int, int, int], None], initial: RGB = (0, 0, 0)) -> None:
        self._sink = sink
        self._smoother.reset(initial)
        self._last_sent = None
        self._last_send_ms = 0
        self._elapsed.restart()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._sink = None

    def set_target(self, r: int, g: int, b: int) -> None:
        self._smoother.set_target((r, g, b))

    def _tick(self) -> None:
        if self._sink is None:
            return
        color = self._smoother.advance()
        now = self._elapsed.elapsed()
        if now - self._last_send_ms < self._send_interval_ms:
            return
        if color == self._last_sent:
            return
        self._last_sent = color
        self._last_send_ms = now
        try:
            self._sink(color[0], color[1], color[2])
        except Exception:
            # A failed BLE write must never kill the stream loop.
            pass

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal

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

    Callers that label their frames (screen sync does; a slider does not) get
    :attr:`frame_coalesced` back for every frame whose colour was replaced by a
    newer one before any tick could act on it. That is the only place a drop can
    be observed honestly — the engine is what displaces frames.
    """

    # (token, frame_id) of a frame whose colour never got its chance to be sent.
    frame_coalesced = Signal(int, int)

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
        self._sink: Callable[..., None] | None = None
        self._labelled_sink = False
        self._last_sent: RGB | None = None
        self._last_send_ms = 0
        self._error_count = 0
        self._last_error = ""
        # The labelled frame currently holding the target, if any. It is cleared
        # by the tick that acts on it and reported as coalesced if a newer frame
        # arrives first.
        self._pending: tuple[int, int] | None = None
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

    def error_count(self) -> int:
        return self._error_count

    def last_error(self) -> str:
        return self._last_error

    def start(
        self,
        sink: Callable[..., None],
        initial: RGB = (0, 0, 0),
        *,
        labelled_sink: bool = False,
    ) -> None:
        """Begin ticking, writing colours to ``sink``.

        A ``labelled_sink`` is called as ``sink(r, g, b, token, frame_id)`` so a
        caller measuring the link can tie the write's outcome back to the frame
        that produced it. Everything else keeps the plain three-argument sink —
        sniffing the signature instead would guess, and guessing wrong here
        means every frame of that mode raising inside the stream loop.
        """
        self._labelled_sink = bool(labelled_sink)
        self._sink = sink
        self._smoother.reset(initial)
        self._last_sent = None
        self._last_send_ms = 0
        self._error_count = 0
        self._last_error = ""
        self._pending = None
        self._elapsed.restart()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._sink = None
        self._pending = None

    def set_target(self, r: int, g: int, b: int, token: int = 0, frame_id: int = 0) -> None:
        """Aim at a colour, optionally saying which frame it came from.

        The pair travels together because a queued signal can arrive after the
        session that produced it has ended; a controller holding only "the last
        frame id" would attribute such a straggler to whatever is running now.
        """
        if self._pending is not None:
            self.frame_coalesced.emit(*self._pending)
        self._pending = (token, frame_id) if frame_id else None
        self._smoother.set_target((r, g, b))

    def _tick(self) -> None:
        if self._sink is None:
            return
        color = self._smoother.advance()
        now = self._elapsed.elapsed()
        if now - self._last_send_ms < self._send_interval_ms:
            return  # still waiting for its turn, not displaced
        # From here the frame has had its chance, whether or not a write follows.
        delivered = self._pending
        self._pending = None
        if color == self._last_sent:
            # The strip already shows this colour. Nothing was lost, so counting
            # a drop here would report a still screen as a failing one — and no
            # command is invented for a write that never happens.
            return
        self._last_sent = color
        self._last_send_ms = now
        try:
            if self._labelled_sink:
                token, frame_id = delivered or (0, 0)
                self._sink(color[0], color[1], color[2], token, frame_id)
            else:
                self._sink(color[0], color[1], color[2])
        except Exception as exc:
            # A failed BLE write must never kill the stream loop, but record it
            # so a persistently failing stream is visible in diagnostics.
            self._error_count += 1
            self._last_error = str(exc)

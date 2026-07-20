"""Reliability helpers for the BLE link — pure, no bleak, no Qt.

Three small pieces the connection layer leans on:

- :func:`reconnect_delay` — how long to wait before the next reconnect attempt.
  Adaptive: a strip that keeps dropping seconds after it reconnects (flapping —
  usually poor range or a failing supply) gets backed off faster than one that
  dropped after a long, healthy session. Optional jitter keeps several strips
  from retrying in lockstep.
- :class:`WritePacer` — keeps consecutive writes a minimum interval apart. Cheap
  controllers silently drop or garble commands that arrive back-to-back.
- :func:`classify_disconnect` — turns whatever the stack reported into a stable
  reason code we can explain to the user. Deliberately conservative: an honest
  "unknown" beats a confidently wrong diagnosis.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

# Backoff ladder for successive reconnect attempts (seconds).
RECONNECT_LADDER: tuple[float, ...] = (2.0, 3.0, 5.0, 8.0, 12.0, 20.0)
# A connection that lasted less than this before dropping again counts as flapping.
FLAPPING_SESSION_SECONDS = 20.0
MIN_RECONNECT_DELAY_SECONDS = 0.5

# ~28 writes/second ceiling for discrete commands.
MIN_WRITE_INTERVAL_SECONDS = 0.035

REASON_MANUAL = "manual"
REASON_OUT_OF_RANGE = "out_of_range"
REASON_STACK_ERROR = "stack_error"
REASON_UNKNOWN = "unknown"

_OUT_OF_RANGE_MARKERS = (
    "not connected",
    "disconnected",
    "unreachable",
    "timeout",
    "timed out",
    "was not found",
    "no longer available",
)
_STACK_ERROR_MARKERS = (
    "access denied",
    "not supported",
    "invalid handle",
    "object has been closed",
    "element not found",
)


def reconnect_delay(
    attempt: int,
    *,
    last_session_seconds: float | None = None,
    jitter: float = 0.0,
    random_unit: Callable[[], float] | None = None,
) -> float:
    """Seconds to wait before reconnect ``attempt`` (1-based).

    ``last_session_seconds`` is how long the previous connection survived; a very
    short one means the link is flapping, so we skip a rung of the ladder instead
    of hammering a strip that clearly isn't ready.

    ``random_unit`` exists so tests can pin the jitter; in production it defaults
    to real randomness, without which several strips would retry in lockstep.
    """
    index = min(max(int(attempt), 1) - 1, len(RECONNECT_LADDER) - 1)
    if last_session_seconds is not None and last_session_seconds < FLAPPING_SESSION_SECONDS:
        index = min(index + 1, len(RECONNECT_LADDER) - 1)
    delay = RECONNECT_LADDER[index]
    if jitter > 0.0:
        unit = (random_unit or random.random)()
        delay += delay * jitter * (unit * 2.0 - 1.0)  # +/- jitter around the rung
    return max(MIN_RECONNECT_DELAY_SECONDS, delay)


class WritePacer:
    """Books write slots so consecutive BLE writes stay ``min_interval`` apart."""

    def __init__(
        self,
        min_interval: float = MIN_WRITE_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._next_free = 0.0

    def reserve(self) -> float:
        """Return how long to wait before writing now, booking that slot."""
        now = self._clock()
        start = max(now, self._next_free)
        self._next_free = start + self._min_interval
        return max(0.0, start - now)

    def reset(self) -> None:
        """Forget the pacing history (e.g. after a reconnect)."""
        self._next_free = 0.0


def classify_disconnect(
    *, manual: bool = False, error_text: str = "", session_seconds: float | None = None
) -> str:
    """A stable reason code for why the link dropped."""
    if manual:
        return REASON_MANUAL
    lowered = str(error_text or "").lower()
    if any(marker in lowered for marker in _STACK_ERROR_MARKERS):
        return REASON_STACK_ERROR
    if any(marker in lowered for marker in _OUT_OF_RANGE_MARKERS):
        return REASON_OUT_OF_RANGE
    # A link that dies almost immediately with nothing to say is usually the strip
    # going away (unplugged or out of range) rather than a stack fault.
    if session_seconds is not None and session_seconds < FLAPPING_SESSION_SECONDS and not lowered:
        return REASON_OUT_OF_RANGE
    return REASON_UNKNOWN

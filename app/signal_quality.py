"""How good a device's signal is, from everything a scan heard about it.

Two questions, deliberately kept apart. *How strong* is answered by the median
of the readings, because one reading is a guess: the same strip five seconds
apart differs by several dB, and the strongest of those is the one a distant
device gets to be judged on if you keep the last reading. *How sure* is answered
by how many readings there were, and it is not the same question — a strip
sitting on the desk may advertise rarely, and calling that a weak signal is a
plain untruth about the hardware.

These are categories of signal, not distance. Transmit power differs between
controllers and sensitivity differs between adapters, so the same room gives
different numbers on different machines. Nothing here converts dB to metres and
nothing should be worded as though it had.

The level of a device depends on that device's own readings and nothing else.
A neighbour turning up with a better aerial cannot re-label the strip in front
of you, which would be the natural consequence of ranking the labels instead of
measuring them.

Pure: numbers in, one answer out. The thresholds are named and live here, so a
live measurement can move them without the shape of the answer changing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Named because they are judgements, not physics. Starting values, to be
# checked against a real scan and moved only if the categories plainly lie —
# not to make some particular strip come out strong.
STRONG_FROM_DBM = -60.0
WEAK_BELOW_DBM = -80.0

# Below this many readings the median is one reading's luck wearing the word
# "median". The device is still listed and still ordered by what was heard; it
# just is not given a confident word for it.
MIN_SAMPLES_FOR_A_LEVEL = 3

# What a receiver can report at all. Outside this it is a library filling a gap
# or a driver returning an error as a number.
MIN_RSSI = -127
MAX_RSSI = 20

LEVEL_STRONG = "strong"
LEVEL_MEDIUM = "medium"
LEVEL_WEAK = "weak"
LEVEL_INSUFFICIENT = "insufficient"


def is_valid_reading(value: Any) -> bool:
    """Whether one value can be believed as a signal reading.

    The single rule. It lives here because this is the module that answers
    questions about readings, and anything else that needs to know — the
    accumulator gathering them during a scan, for one — asks rather than
    restates. Two copies of a range is one range that quietly stops matching.

    ``bool`` is excluded on purpose: it is an ``int`` in Python, so ``True``
    would otherwise be counted as a reading of one, which is inside the range
    and would drag a median up by a hundred dB.

    An explicit finiteness check is redundant here: infinities fall outside the
    range and NaN fails the chained comparison.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return MIN_RSSI <= float(value) <= MAX_RSSI


def valid_readings(samples: Any) -> list[float]:
    """The readings that can be believed, in the order they arrived.

    Filtered again here even though the accumulator already filters — by the
    same rule, which is the point. This function is the one that answers, and
    an answer that is only correct because of what some other module did
    earlier is correct by arrangement; the arrangement is the first thing to go
    when a second caller appears.
    """
    return [float(value) for value in samples or () if is_valid_reading(value)]


def median_of(readings: list[float]) -> float | None:
    """The middle reading, or the midpoint of the two middle ones."""
    if not readings:
        return None
    ordered = sorted(readings)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


@dataclass(frozen=True)
class SignalQuality:
    """What one scan is entitled to say about one device's signal."""

    # Kept as a number whatever the level says. It orders the list, and it goes
    # into a report where somebody debugging needs the figure rather than the
    # word. ``None`` only when there was nothing believable to take it from.
    median: float | None = None
    samples: int = 0
    level: str = LEVEL_INSUFFICIENT

    @property
    def is_confident(self) -> bool:
        return self.level != LEVEL_INSUFFICIENT


def measure(samples: Any) -> SignalQuality:
    """Judge one device by its own readings and nothing else."""
    readings = valid_readings(samples)
    median = median_of(readings)
    if len(readings) < MIN_SAMPLES_FOR_A_LEVEL or median is None:
        return SignalQuality(median=median, samples=len(readings), level=LEVEL_INSUFFICIENT)
    if median >= STRONG_FROM_DBM:
        level = LEVEL_STRONG
    elif median >= WEAK_BELOW_DBM:
        level = LEVEL_MEDIUM
    else:
        level = LEVEL_WEAK
    return SignalQuality(median=median, samples=len(readings), level=level)

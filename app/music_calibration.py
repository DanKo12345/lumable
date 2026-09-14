"""Setting the microphone gate from a few seconds of the room's own silence.

The person presses Calibrate and keeps quiet. The first half second of sound is
thrown away — a device that has just opened clicks and settles — and the next
three seconds are measured. Both are counted in the audio actually received, not
by the wall clock: a device that delivers late must not be judged on half a
measurement.

The gate goes a margin above what the room does most of the time. What the
measurement is allowed to contain is decided against the room's median, not
against the result: a voice that fills a tenth of the measurement lifts the
95th percentile, and a test against the gate about to be set would then pass
the very voice it should have caught.

Pure arithmetic, no Qt, so every case can be fed a synthetic room.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.music_gate import ANALYSER_OPENS_AT_RMS, GATE_DB_DEFAULT, db_for_slider, slider_for_db

# Audio thrown away while the device settles, then audio measured.
WARMUP_S = 0.5
MEASURE_S = 3.0
# Wall-clock limit for the whole run. A device that hands nothing over is a
# capture problem, not a quiet room.
TIMEOUT_S = 6.0
# Fewer blocks than this is not a measurement, however long they claim to be.
MIN_BLOCKS = 20

# The gate sits this far above the room's 95th percentile.
MARGIN_DB = 8.0
# A block this far above the room's median is something happening in the room.
UNSTABLE_ABOVE_MEDIAN_DB = 12.0
UNSTABLE_SHARE = 0.02
# A gate this high would cut quiet music and speech: the room is too noisy to
# calibrate against, and it also catches speech steady enough to look like a floor.
TOO_NOISY_DB = -30.0
# Rounding up to a slider position forgives this much, in slider units (about
# 0.00006 dB). A room measured exactly on a position then stays on it instead of
# being pushed a whole step up by the last bits of a float32 sample.
ROUNDING_SLACK = 1e-4

OK = "ok"
CLIPPED = "clipped"
UNSTABLE = "unstable"
TOO_NOISY = "too_noisy"
NO_AUDIO = "no_audio"


class NoiseSample:
    """One capture session's blocks, counted by the audio they hold.

    Fed from the capture thread one block at a time and read from the interface;
    a list append and a float are all either side touches.
    """

    def __init__(self, session_token: int) -> None:
        self.session_token = session_token
        self._heard = 0.0
        self._measured = 0.0
        self._rms: list[float] = []
        self._clipped = False
        self._broken = False

    def add(self, seconds: float, rms: float, clipped: bool) -> None:
        if self.complete:
            return
        try:
            rms = float(rms)
        except (TypeError, ValueError):
            rms = math.nan
        if not (math.isfinite(rms) and rms >= 0.0):
            # Not a level at all, even while the device settles. The measurement
            # ends here and carries the broken value on to be judged.
            self._rms.append(math.nan)
            self._broken = True
            return
        if not float(seconds) > 0.0:
            return  # a block with no audio in it is no time in the room
        started = self._heard
        self._heard += max(0.0, float(seconds))
        if started < WARMUP_S:
            return  # the device settling, including its clicks and pops
        self._rms.append(float(rms))
        self._clipped = self._clipped or bool(clipped)
        self._measured += max(0.0, float(seconds))

    @property
    def measured_seconds(self) -> float:
        return self._measured

    @property
    def complete(self) -> bool:
        return self._broken or self._measured >= MEASURE_S

    def snapshot(self) -> tuple[tuple[float, ...], bool, float]:
        return tuple(self._rms), self._clipped, self._measured


@dataclass(frozen=True)
class Calibration:
    outcome: str
    # Only for OK: the slider position and the threshold it stands for.
    position: int | None = None
    gate_db: float | None = None
    median_db: float | None = None
    p95_db: float | None = None


def _percentile(sorted_values: list[float], share: float) -> float:
    index = max(0, math.ceil(share * len(sorted_values)) - 1)
    return sorted_values[index]


def _db(rms: float) -> float:
    return 20.0 * math.log10(rms) if rms > 0.0 else -math.inf


def judge(rms_values, clipped: bool, measured_seconds: float) -> Calibration:
    values = [float(value) for value in rms_values]
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        # A level that is not a number, endless or below zero is a broken
        # signal, whatever the rest of the room did. Never a quiet room.
        return Calibration(NO_AUDIO)
    values.sort()
    if len(values) < MIN_BLOCKS or measured_seconds < MEASURE_S:
        return Calibration(NO_AUDIO)
    if clipped:
        return Calibration(CLIPPED)
    median = _percentile(values, 0.5)
    p95 = _percentile(values, 0.95)
    median_db, p95_db = _db(median), _db(p95)
    limit = max(median, ANALYSER_OPENS_AT_RMS) * 10.0 ** (UNSTABLE_ABOVE_MEDIAN_DB / 20.0)
    if sum(1 for value in values if value > limit) / len(values) > UNSTABLE_SHARE:
        return Calibration(UNSTABLE, median_db=median_db, p95_db=p95_db)
    threshold = max(p95_db + MARGIN_DB, GATE_DB_DEFAULT)
    if threshold > TOO_NOISY_DB:
        return Calibration(TOO_NOISY, median_db=median_db, p95_db=p95_db)
    # The slider has 101 positions. Rounded up, so the gate is never set below
    # the margin that was measured for.
    position = min(100, math.ceil(slider_for_db(threshold) - ROUNDING_SLACK))
    return Calibration(OK, position, db_for_slider(position), median_db, p95_db)

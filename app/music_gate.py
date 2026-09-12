"""The microphone's noise gate, in decibels.

The gate used to be a linear slider: 0..100 % of an eighth of full scale. A
quiet microphone's whole working range — the room near -70 dBFS, speech around
-30 — then sat in the first few pixels of the track, where the room's level
could not be seen and the handle moved in steps many times larger than the
room. The slider now spans -70..-10 dBFS evenly, so every position is the same
audible step.

Pure arithmetic, no Qt: the settings, the engine and the card all take their
numbers from here, so the handle, the stored value and the gate cannot part.
"""

from __future__ import annotations

import math

GATE_DB_MIN = -70.0
GATE_DB_MAX = -10.0

# Where the analyser opens by itself at the very least: its lowest believable
# floor times its opening ratio (see music_analysis). A manual gate below this
# changes nothing, so a new installation starts here rather than above speech.
ANALYSER_OPENS_AT_RMS = 0.0006 * 2.6

# How the old linear slider became an RMS: percent / 100 * 0.5 * 0.25.
LEGACY_RMS_PER_PERCENT = 0.5 * 0.25 / 100.0


def _clamp_db(db: float) -> float:
    return max(GATE_DB_MIN, min(GATE_DB_MAX, float(db)))


def rms_for_db(db: float) -> float:
    return 10.0 ** (float(db) / 20.0)


def db_for_rms(rms: float) -> float:
    """An RMS in dBFS on the slider's range. Silence reads as the bottom."""
    if rms <= 0.0:
        return GATE_DB_MIN
    return _clamp_db(20.0 * math.log10(rms))


def db_for_slider(value: float) -> float:
    ratio = max(0.0, min(100.0, float(value))) / 100.0
    return GATE_DB_MIN + ratio * (GATE_DB_MAX - GATE_DB_MIN)


def slider_for_db(db: float) -> float:
    return (_clamp_db(db) - GATE_DB_MIN) / (GATE_DB_MAX - GATE_DB_MIN) * 100.0


def slider_for_rms(rms: float) -> float:
    return slider_for_db(db_for_rms(rms))


def rms_for_slider(value: float) -> float:
    return rms_for_db(db_for_slider(value))


GATE_DB_DEFAULT = round(db_for_rms(ANALYSER_OPENS_AT_RMS), 1)


def gate_db_from_saved(music: object) -> float:
    """The saved threshold in dBFS, whichever format it was saved in.

    ``gate_db`` is the current format. Its absence means a file written before
    it: an old ``gate`` percent is carried over as the same RMS, so a threshold
    someone set keeps meaning what it meant. Neither key means nothing was ever
    chosen, and the gate starts at the analyser's own lowest threshold.
    """
    if isinstance(music, dict):
        if "gate_db" in music:
            try:
                value = float(music["gate_db"])
            except (TypeError, ValueError):
                return GATE_DB_DEFAULT
            return _clamp_db(value) if math.isfinite(value) else GATE_DB_DEFAULT
        if "gate" in music:
            try:
                percent = float(music["gate"])
            except (TypeError, ValueError):
                return GATE_DB_DEFAULT
            if not math.isfinite(percent):
                return GATE_DB_DEFAULT
            percent = max(0.0, min(100.0, percent))
            return round(db_for_rms(percent * LEGACY_RMS_PER_PERCENT), 2)
    return GATE_DB_DEFAULT


def format_db(db: float) -> str:
    """A whole number of decibels, with a true minus sign."""
    value = round(float(db))
    return f"−{abs(value)}" if value < 0 else str(value)

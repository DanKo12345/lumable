from __future__ import annotations

# Pure maths for the sunrise / sleep light timers.
#
# Both are a brightness ramp of a fixed colour over a duration:
#   • sleep   — fade the current colour from full to off (level 1 → 0),
#   • sunrise — grow the target colour from off to full (level 0 → 1).
# A smoothstep easing makes the ends gentle (no abrupt start/finish). Everything
# here is pure and dependency-free so it's unit-testable; the controller does the
# BLE writes and timing.

RGB = tuple[int, int, int]

SLEEP = "sleep"
SUNRISE = "sunrise"

SECONDS_PER_DAY = 86_400
MIN_MINUTES = 1
MAX_MINUTES = 120


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def eased(fraction: float) -> float:
    """Smoothstep easing (gentle at both ends), input/clamped to 0..1."""
    f = clamp01(fraction)
    return f * f * (3.0 - 2.0 * f)


def progress(elapsed_seconds: float, duration_seconds: float) -> float:
    """0..1 fraction of the ramp completed (1.0 once the duration is up)."""
    if duration_seconds <= 0:
        return 1.0
    return clamp01(elapsed_seconds / duration_seconds)


def ramp_level(elapsed_seconds: float, duration_seconds: float, *, kind: str) -> float:
    """Eased brightness multiplier (0..1) at ``elapsed_seconds`` into the ramp.

    ``kind`` SLEEP counts down (1 → 0); SUNRISE counts up (0 → 1).
    """
    e = eased(progress(elapsed_seconds, duration_seconds))
    return 1.0 - e if kind == SLEEP else e


def scale_rgb(rgb: RGB, level: float) -> RGB:
    """Dim ``rgb`` by ``level`` (0..1), clamped to valid channel bytes."""
    level = clamp01(level)
    return (
        max(0, min(255, round(rgb[0] * level))),
        max(0, min(255, round(rgb[1] * level))),
        max(0, min(255, round(rgb[2] * level))),
    )


def seconds_until(now_seconds: int, target_seconds: int) -> int:
    """Seconds from ``now`` to the next occurrence of ``target`` (both seconds-of-
    day). If the target already passed today, it rolls over to tomorrow."""
    now_seconds %= SECONDS_PER_DAY
    target_seconds %= SECONDS_PER_DAY
    return (target_seconds - now_seconds) % SECONDS_PER_DAY


def hm_to_seconds(hours: int, minutes: int) -> int:
    return (int(hours) % 24) * 3600 + (int(minutes) % 60) * 60


def sunrise_elapsed(now_seconds: int, target_seconds: int, duration_seconds: int) -> int | None:
    """Seconds into the sunrise ramp at ``now``, or ``None`` if ``now`` is outside
    the ``[target - duration, target]`` window (handles wrap over midnight).

    Pure, so the "in window / before / after / missed" logic is unit-testable.
    """
    window_start = (int(target_seconds) - int(duration_seconds)) % SECONDS_PER_DAY
    elapsed = (int(now_seconds) - window_start) % SECONDS_PER_DAY
    return elapsed if elapsed <= max(0, int(duration_seconds)) else None

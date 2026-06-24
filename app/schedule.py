from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QTime


def is_scheduled_day(weekday: int, days) -> bool:
    """Whether the schedule should run on ``weekday`` (0 = Monday .. 6 = Sunday).

    ``days`` is the set of enabled weekdays (same 0..6 convention). An empty
    selection means no day is scheduled. Pure, so it's unit-testable.
    """
    try:
        return int(weekday) in {int(day) for day in days}
    except (TypeError, ValueError):
        return False


def should_fire_schedule_time(now: QTime, scheduled: QTime, *, missed_window_minutes: int) -> bool:
    if not now.isValid() or not scheduled.isValid():
        return False
    if now < scheduled:
        return False
    seconds_after = scheduled.secsTo(now)
    return 0 <= seconds_after <= max(0, int(missed_window_minutes)) * 60

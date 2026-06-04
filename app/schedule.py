from __future__ import annotations

from PySide6.QtCore import QTime


def should_fire_schedule_time(now: QTime, scheduled: QTime, *, missed_window_minutes: int) -> bool:
    if not now.isValid() or not scheduled.isValid():
        return False
    if now < scheduled:
        return False
    seconds_after = scheduled.secsTo(now)
    return 0 <= seconds_after <= max(0, int(missed_window_minutes)) * 60

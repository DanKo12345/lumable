from __future__ import annotations

from PySide6.QtCore import QTime

from app.schedule import should_fire_schedule_time


def test_schedule_fires_on_exact_minute() -> None:
    assert should_fire_schedule_time(QTime(19, 0, 0), QTime(19, 0), missed_window_minutes=5) is True


def test_schedule_fires_when_recently_missed() -> None:
    assert should_fire_schedule_time(QTime(19, 4, 59), QTime(19, 0), missed_window_minutes=5) is True


def test_schedule_does_not_fire_after_missed_window() -> None:
    assert should_fire_schedule_time(QTime(19, 5, 1), QTime(19, 0), missed_window_minutes=5) is False


def test_schedule_does_not_fire_before_scheduled_time() -> None:
    assert should_fire_schedule_time(QTime(18, 59, 59), QTime(19, 0), missed_window_minutes=5) is False


def test_schedule_does_not_treat_yesterday_time_as_recent_after_midnight() -> None:
    assert should_fire_schedule_time(QTime(0, 1), QTime(23, 59), missed_window_minutes=5) is False

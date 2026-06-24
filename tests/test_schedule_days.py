from __future__ import annotations

from app.schedule import is_scheduled_day
from app.storage import validate_schedule


def test_is_scheduled_day_weekdays_only() -> None:
    weekdays = [0, 1, 2, 3, 4]  # Mon..Fri
    assert is_scheduled_day(0, weekdays) is True  # Monday
    assert is_scheduled_day(4, weekdays) is True  # Friday
    assert is_scheduled_day(5, weekdays) is False  # Saturday
    assert is_scheduled_day(6, weekdays) is False  # Sunday


def test_is_scheduled_day_all_and_none() -> None:
    every_day = [0, 1, 2, 3, 4, 5, 6]
    assert all(is_scheduled_day(d, every_day) for d in range(7))
    # Empty selection -> never scheduled.
    assert not any(is_scheduled_day(d, []) for d in range(7))


def test_validate_schedule_days_default_all_when_missing() -> None:
    result = validate_schedule({"on_time": "08:00"})
    assert result["days"] == [0, 1, 2, 3, 4, 5, 6]


def test_validate_schedule_days_cleaned_and_sorted() -> None:
    result = validate_schedule({"days": [6, 0, 0, 9, -1, 3, "x"]})
    assert result["days"] == [0, 3, 6]  # deduped, in-range, sorted


def test_validate_schedule_days_empty_allowed() -> None:
    assert validate_schedule({"days": []})["days"] == []


def test_validate_schedule_days_non_list_falls_back() -> None:
    assert validate_schedule({"days": "weekdays"})["days"] == [0, 1, 2, 3, 4, 5, 6]

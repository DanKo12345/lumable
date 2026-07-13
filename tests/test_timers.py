from __future__ import annotations

from app.timers import (
    SLEEP,
    SUNRISE,
    eased,
    hm_to_seconds,
    ramp_level,
    scale_rgb,
    seconds_until,
    sunrise_elapsed,
)


def test_eased_is_gentle_and_monotonic() -> None:
    assert eased(0.0) == 0.0
    assert eased(1.0) == 1.0
    assert eased(0.5) == 0.5
    # Slow start: less than linear near the beginning.
    assert eased(0.1) < 0.1
    assert eased(-1.0) == 0.0  # clamped
    assert eased(2.0) == 1.0


def test_sleep_ramp_counts_down() -> None:
    assert ramp_level(0, 600, kind=SLEEP) == 1.0     # starts at full
    assert ramp_level(600, 600, kind=SLEEP) == 0.0   # ends off
    assert ramp_level(900, 600, kind=SLEEP) == 0.0   # past the end -> stays off
    assert 0.0 < ramp_level(300, 600, kind=SLEEP) < 1.0


def test_sunrise_ramp_counts_up() -> None:
    assert ramp_level(0, 600, kind=SUNRISE) == 0.0   # starts off
    assert ramp_level(600, 600, kind=SUNRISE) == 1.0  # ends full
    assert ramp_level(1200, 600, kind=SUNRISE) == 1.0  # clamped
    assert 0.0 < ramp_level(300, 600, kind=SUNRISE) < 1.0


def test_zero_duration_is_instantly_complete() -> None:
    assert ramp_level(0, 0, kind=SUNRISE) == 1.0
    assert ramp_level(0, 0, kind=SLEEP) == 0.0


def test_scale_rgb_dims_and_clamps() -> None:
    assert scale_rgb((255, 100, 40), 1.0) == (255, 100, 40)
    assert scale_rgb((255, 100, 40), 0.0) == (0, 0, 0)
    assert scale_rgb((200, 200, 200), 0.5) == (100, 100, 100)
    assert scale_rgb((255, 255, 255), 2.0) == (255, 255, 255)  # level clamped


def test_seconds_until_rolls_over_midnight() -> None:
    assert seconds_until(hm_to_seconds(7, 0), hm_to_seconds(7, 30)) == 30 * 60
    # Target already passed today -> next day.
    assert seconds_until(hm_to_seconds(8, 0), hm_to_seconds(7, 0)) == 23 * 3600
    assert seconds_until(hm_to_seconds(7, 0), hm_to_seconds(7, 0)) == 0


def test_hm_to_seconds_wraps() -> None:
    assert hm_to_seconds(0, 0) == 0
    assert hm_to_seconds(23, 59) == 23 * 3600 + 59 * 60
    assert hm_to_seconds(25, 61) == 1 * 3600 + 1 * 60  # wrapped


def test_sunrise_elapsed_inside_window() -> None:
    target = hm_to_seconds(7, 0)
    duration = 20 * 60
    # Right at the window start -> elapsed 0.
    assert sunrise_elapsed(target - duration, target, duration) == 0
    # Halfway through.
    assert sunrise_elapsed(target - duration // 2, target, duration) == duration // 2
    # Exactly at the target -> elapsed equals duration (finalises).
    assert sunrise_elapsed(target, target, duration) == duration


def test_sunrise_elapsed_outside_window_is_none() -> None:
    target = hm_to_seconds(7, 0)
    duration = 20 * 60
    # One second before the window opens.
    assert sunrise_elapsed(target - duration - 1, target, duration) is None
    # After the target has passed.
    assert sunrise_elapsed(target + 60, target, duration) is None


def test_sunrise_elapsed_wraps_across_midnight() -> None:
    target = hm_to_seconds(0, 10)  # 00:10
    duration = 20 * 60             # window opens at 23:50 the previous day
    # 23:55 is inside the window that straddles midnight.
    assert sunrise_elapsed(hm_to_seconds(23, 55), target, duration) == 5 * 60
    # 00:05 is still inside.
    assert sunrise_elapsed(hm_to_seconds(0, 5), target, duration) == 15 * 60
    # 00:15 is past the target.
    assert sunrise_elapsed(hm_to_seconds(0, 15), target, duration) is None

"""Windows session and power events: read once, delivered once.

Windows is generous with these. Waking a laptop usually delivers two resume
messages, and a rule that dims on sleep and restores on wake would otherwise
fire twice and could interleave with itself.
"""

from __future__ import annotations

from app.windows_session import (
    EVENT_LOCKED,
    EVENT_SLEEP,
    EVENT_UNLOCKED,
    EVENT_WAKE,
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMRESUMESUSPEND,
    PBT_APMSUSPEND,
    REPEAT_WINDOW_SECONDS,
    WM_POWERBROADCAST,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    WTS_SESSION_UNLOCK,
    SessionEvents,
    classify,
)


def test_each_message_means_what_it_says() -> None:
    assert classify(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK) == EVENT_LOCKED
    assert classify(WM_WTSSESSION_CHANGE, WTS_SESSION_UNLOCK) == EVENT_UNLOCKED
    assert classify(WM_POWERBROADCAST, PBT_APMSUSPEND) == EVENT_SLEEP


def test_both_resume_reasons_are_one_waking_up() -> None:
    """Windows sends the automatic one and the user's one; a person woke a
    computer once."""
    assert classify(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC) == EVENT_WAKE
    assert classify(WM_POWERBROADCAST, PBT_APMRESUMESUSPEND) == EVENT_WAKE


def test_anything_else_is_not_ours() -> None:
    assert classify(WM_WTSSESSION_CHANGE, 0x1) is None  # console connect
    assert classify(0x0010, WTS_SESSION_LOCK) is None  # WM_CLOSE
    assert classify(WM_POWERBROADCAST, 0xFF) is None


def test_the_resume_pair_wakes_the_strip_once() -> None:
    events = SessionEvents(repeat_window=5.0)

    first = events.note(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC, now=100.0)
    second = events.note(WM_POWERBROADCAST, PBT_APMRESUMESUSPEND, now=100.05)

    assert first == EVENT_WAKE
    assert second is None


def test_the_same_thing_happening_again_later_is_a_new_event() -> None:
    """Locking, unlocking and locking again in a minute is three things, not
    one — the collapse is for a burst, not for a habit."""
    events = SessionEvents(repeat_window=5.0)

    assert events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=100.0) == EVENT_LOCKED
    assert events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=106.0) == EVENT_LOCKED


def test_different_events_do_not_silence_each_other() -> None:
    events = SessionEvents(repeat_window=5.0)

    assert events.note(WM_POWERBROADCAST, PBT_APMSUSPEND, now=100.0) == EVENT_SLEEP
    assert events.note(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC, now=100.1) == EVENT_WAKE


def test_an_unlock_without_a_lock_still_counts() -> None:
    """That is what signing in looks like. Refusing it to keep the bookkeeping
    tidy would lose a real event."""
    events = SessionEvents()

    assert events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_UNLOCK, now=1.0) == EVENT_UNLOCKED


def test_restarting_the_listener_forgets_what_it_heard() -> None:
    """A new registration must not be silenced by the old one's history: the
    machine may have locked while nobody was listening."""
    events = SessionEvents(repeat_window=60.0)
    events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=100.0)

    events.reset()

    assert events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=100.5) == EVENT_LOCKED


def test_the_default_window_collapses_a_burst_and_not_a_habit() -> None:
    """Checked against the shipped constant, not one the test picked: a window
    of an hour would turn "locked, unlocked, locked again" into one event."""
    assert 1.0 <= REPEAT_WINDOW_SECONDS <= 15.0

    events = SessionEvents()
    assert events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=0.0) == EVENT_LOCKED
    assert events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=0.2) is None
    later = REPEAT_WINDOW_SECONDS + 1.0
    assert events.note(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=later) == EVENT_LOCKED

"""Reading Windows session and power messages, without Qt or ctypes.

The window layer receives a message id and a wParam; deciding what they mean —
and whether the app has already heard it — is arithmetic, so it lives here where
it can be tested without locking a real machine.

Windows is generous with these. Waking a laptop usually delivers *two* resume
messages, one for the automatic wake and one for the user's, and a lid opened
twice in a second can produce the pair again. A rule that dims the strip on sleep
and restores it on wake would fire twice and, worse, could interleave with itself
— so repeats of the same event inside a short window are collapsed here rather
than left for every listener to notice.
"""

from __future__ import annotations

# The two messages worth listening to.
WM_WTSSESSION_CHANGE = 0x02B1
WM_POWERBROADCAST = 0x0218

# Session change reasons (wParam of WM_WTSSESSION_CHANGE).
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

# Power broadcast reasons (wParam of WM_POWERBROADCAST).
PBT_APMSUSPEND = 0x4
PBT_APMRESUMESUSPEND = 0x7
PBT_APMRESUMEAUTOMATIC = 0x12

# What the app calls them.
EVENT_LOCKED = "windows_locked"
EVENT_UNLOCKED = "windows_unlocked"
EVENT_SLEEP = "windows_sleep"
EVENT_WAKE = "windows_wake"

SESSION_EVENTS: tuple[str, ...] = (EVENT_LOCKED, EVENT_UNLOCKED, EVENT_SLEEP, EVENT_WAKE)

# Both resume reasons mean the same thing to us, and Windows often sends both.
_MESSAGES: dict[int, dict[int, str]] = {
    WM_WTSSESSION_CHANGE: {
        WTS_SESSION_LOCK: EVENT_LOCKED,
        WTS_SESSION_UNLOCK: EVENT_UNLOCKED,
    },
    WM_POWERBROADCAST: {
        PBT_APMSUSPEND: EVENT_SLEEP,
        PBT_APMRESUMESUSPEND: EVENT_WAKE,
        PBT_APMRESUMEAUTOMATIC: EVENT_WAKE,
    },
}

# Long enough to swallow the resume pair, short enough that locking, unlocking
# and locking again in ten seconds still reads as three things happening.
REPEAT_WINDOW_SECONDS = 5.0


def classify(message: int, wparam: int) -> str | None:
    """The event a raw message means, or ``None`` if it means nothing to us."""
    return _MESSAGES.get(int(message), {}).get(int(wparam))


class SessionEvents:
    """Turns raw messages into events, once each.

    Deliberately not a filter on *what* may follow *what*: an unlock without a
    preceding lock is what a fresh sign-in looks like, and refusing it would lose
    a real event to tidy bookkeeping. Only exact repeats are collapsed.
    """

    def __init__(self, repeat_window: float = REPEAT_WINDOW_SECONDS) -> None:
        self._window = float(repeat_window)
        self._last: dict[str, float] = {}

    def note(self, message: int, wparam: int, now: float) -> str | None:
        """The event to deliver, or ``None`` for noise and repeats."""
        event = classify(message, wparam)
        if event is None:
            return None
        previous = self._last.get(event)
        if previous is not None and 0.0 <= now - previous < self._window:
            return None
        self._last[event] = now
        return event

    def reset(self) -> None:
        """Forget what has been seen — used when the listener is restarted, so a
        new registration is not silenced by the old one's history."""
        self._last.clear()

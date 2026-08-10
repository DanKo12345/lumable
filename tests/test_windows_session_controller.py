"""The listener and the path from a Windows message to an automation.

Its own native filter and its own WTS registration, kept apart from the hotkey
controller's. Qt calls every installed filter in turn and the hotkey one already
returns "not mine" for anything but WM_HOTKEY, so two cost nothing — that was
measured before this was written, not assumed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication, QWidget

from app.automation.runtime import (
    EVENT_WINDOWS_LOCKED,
    EVENT_WINDOWS_SLEEP,
    EVENT_WINDOWS_WAKE,
)
from app.windows_session import (
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMRESUMESUSPEND,
    PBT_APMSUSPEND,
    WM_POWERBROADCAST,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    WTS_SESSION_UNLOCK,
)
from app.windows_session_controller import WindowsSessionController


def test_native_filter_base_is_first_in_the_mro() -> None:
    """PySide6 silently skips filters whose QObject base comes first."""
    assert WindowsSessionController.__bases__[0] is QAbstractNativeEventFilter


def _require_real_window(controller) -> None:
    """Registration needs a native window handle, which the offscreen platform
    the suite runs on does not provide. The call itself was verified against a
    real window before this was written; what is skipped here is the platform,
    not the behaviour."""
    if not controller.start():
        pytest.skip("no native window handle under the offscreen platform")


def _message(message: int, wparam: int):
    """A real MSG the filter can parse, so the tests reach the code past it —
    an unparseable pointer makes every branch look the same."""
    import ctypes
    from ctypes import wintypes

    msg = wintypes.MSG()
    msg.message = message
    msg.wParam = wparam
    return msg, ctypes.addressof(msg)


def _pretend_registered(controller) -> None:
    """Route messages without a registration. Everything below the registration
    — classification, collapsing, signalling — is the same code either way."""
    controller._registered_hwnd = 1


@pytest.fixture()
def listener():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.show()
    app.processEvents()
    controller = WindowsSessionController(host)
    try:
        yield controller
    finally:
        controller.stop()
        host.close()


def test_it_registers_and_hands_the_registration_back(listener) -> None:
    _require_real_window(listener)
    assert listener._registered_hwnd is not None

    listener.stop()

    assert listener._registered_hwnd is None


def test_starting_twice_registers_once(listener) -> None:
    _require_real_window(listener)
    first = listener._registered_hwnd

    assert listener.start() is True
    assert listener._registered_hwnd == first


def test_stopping_twice_is_not_an_error(listener) -> None:
    listener.start()  # may not register offscreen; stopping must cope either way
    listener.stop()
    listener.stop()  # on the way out, where an exception takes the shutdown too

    assert listener._registered_hwnd is None


def test_it_can_be_started_again_after_being_stopped(listener) -> None:
    """The window can be hidden to the tray and brought back."""
    _require_real_window(listener)
    listener.stop()

    assert listener.start() is True


def test_messages_are_ignored_until_the_listener_is_registered(listener) -> None:
    """The gate is in the filter, where messages actually arrive — before a
    registration the app has not asked for these and must not act on whatever
    else is passing through the queue."""
    heard: list[str] = []
    listener.session_event.connect(heard.append)
    _keep_alive, pointer = _message(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK)

    handled, _ = listener.nativeEventFilter(b"windows_generic_MSG", pointer)

    assert handled is False
    assert heard == [], "a lock arriving before we asked is not ours to act on"


def test_each_event_reaches_its_own_signal(listener) -> None:
    _pretend_registered(listener)
    heard: list[str] = []
    named: list[str] = []
    listener.session_event.connect(heard.append)
    listener.locked.connect(lambda: named.append("locked"))
    listener.slept.connect(lambda: named.append("slept"))
    listener.woke.connect(lambda: named.append("woke"))

    listener.deliver(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=1.0)
    listener.deliver(WM_WTSSESSION_CHANGE, WTS_SESSION_UNLOCK, now=2.0)
    listener.deliver(WM_POWERBROADCAST, PBT_APMSUSPEND, now=3.0)
    listener.deliver(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC, now=4.0)

    assert heard == [
        "windows_locked",
        "windows_unlocked",
        "windows_sleep",
        "windows_wake",
    ]
    assert named == ["locked", "slept", "woke"]


def test_the_resume_pair_is_delivered_once(listener) -> None:
    _pretend_registered(listener)
    heard: list[str] = []
    listener.session_event.connect(heard.append)

    listener.deliver(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC, now=10.0)
    listener.deliver(WM_POWERBROADCAST, PBT_APMRESUMESUSPEND, now=10.1)

    assert heard == ["windows_wake"]


def test_a_restart_hears_the_next_event_even_if_it_repeats(listener) -> None:
    _pretend_registered(listener)
    heard: list[str] = []
    listener.session_event.connect(heard.append)
    listener.deliver(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=100.0)

    listener.stop()  # stopping is what forgets
    _pretend_registered(listener)
    listener.deliver(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, now=100.5)

    assert heard == ["windows_locked", "windows_locked"]


def test_it_never_swallows_a_broadcast(listener) -> None:
    """These are broadcasts. Claiming one would take it from every other
    listener in the process, Qt's own included."""
    _pretend_registered(listener)
    heard: list[str] = []
    listener.session_event.connect(heard.append)
    _keep_alive, pointer = _message(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK)

    handled, _ = listener.nativeEventFilter(b"windows_generic_MSG", pointer)

    assert handled is False, "a broadcast belongs to everyone listening"
    assert heard == ["windows_locked"], "and it still has to be read"


# ── the path into the engine ──────────────────────────────────────────
class _Queue:
    """The real note_windows_event, bound to nothing but a pending list."""

    def __init__(self) -> None:
        from app.automation.runtime import AutomationRuntime

        self._pending: list[str] = []
        self.note_windows_event = AutomationRuntime.note_windows_event.__get__(self)


def test_an_unknown_event_is_dropped_rather_than_queued() -> None:
    """A name nobody understands would otherwise sit in the queue forever."""
    runtime = _Queue()

    assert runtime.note_windows_event("windows_exploded") is False
    assert runtime._pending == []
    assert runtime.note_windows_event(EVENT_WINDOWS_LOCKED) is True
    assert runtime._pending == [EVENT_WINDOWS_LOCKED]


def test_the_four_events_are_the_ones_the_engine_knows() -> None:
    from app.automation.rules import (
        EDGE_TRIGGERS,
        TRIGGER_WINDOWS_LOCKED,
        TRIGGER_WINDOWS_SLEEP,
        TRIGGER_WINDOWS_UNLOCKED,
        TRIGGER_WINDOWS_WAKE,
    )
    from app.automation.runtime import WINDOWS_EVENTS

    # The event names and the trigger kinds are the same strings on purpose: the
    # resolver matches an edge event to a rule by name, so a mismatch would be a
    # rule that can be created and never fires.
    assert set(WINDOWS_EVENTS) == {
        TRIGGER_WINDOWS_LOCKED,
        TRIGGER_WINDOWS_UNLOCKED,
        TRIGGER_WINDOWS_SLEEP,
        TRIGGER_WINDOWS_WAKE,
    }
    for kind in WINDOWS_EVENTS:
        assert kind in EDGE_TRIGGERS, "these are moments, not conditions to poll"


def test_sleep_is_an_edge_because_it_cannot_be_polled() -> None:
    """By the time sleeping could be observed as a state, nothing is running to
    observe it."""
    from app.automation.rules import STATEFUL_TRIGGERS

    assert EVENT_WINDOWS_SLEEP not in STATEFUL_TRIGGERS
    assert EVENT_WINDOWS_WAKE not in STATEFUL_TRIGGERS


# ── waking up before Bluetooth does ───────────────────────────────────
class _Runtime2:
    """Just enough of the runtime to exercise _take_pending."""

    def __init__(self, connected: bool) -> None:
        from app.automation.runtime import AutomationRuntime

        self._pending: list[str] = []
        self._held_wake_since = None
        self.connected = connected
        self._take_pending = AutomationRuntime._take_pending.__get__(self)
        self._connected = lambda: self.connected


def test_a_wake_waits_for_the_strip_instead_of_being_skipped() -> None:
    """Windows says "awake" while Bluetooth is still coming back. Firing there
    would have the rule skipped as disconnected and never run — which for
    "restore my light when I wake" is the whole feature missing."""
    runtime = _Runtime2(connected=False)
    runtime._pending.append(EVENT_WINDOWS_WAKE)

    assert runtime._take_pending() == []
    assert runtime._pending == [EVENT_WINDOWS_WAKE], "the wake is still waiting"

    runtime.connected = True
    assert runtime._take_pending() == [EVENT_WINDOWS_WAKE]


def test_locking_and_sleeping_need_no_strip_and_are_not_held() -> None:
    """They usually turn the light off. Holding them until a strip that is going
    away comes back would mean the light stays on all night."""
    runtime = _Runtime2(connected=False)
    runtime._pending.extend([EVENT_WINDOWS_LOCKED, EVENT_WINDOWS_SLEEP])

    taken = runtime._take_pending()

    assert taken == [EVENT_WINDOWS_LOCKED, EVENT_WINDOWS_SLEEP]
    assert runtime._pending == []


def test_a_wake_is_dropped_rather_than_applied_much_later(monkeypatch) -> None:
    """A scene applied two minutes after someone sat down is a light turning on
    by itself."""
    import app.automation.runtime as module

    runtime = _Runtime2(connected=False)
    runtime._pending.append(EVENT_WINDOWS_WAKE)

    clock = [1000.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    runtime._take_pending()
    assert runtime._pending == [EVENT_WINDOWS_WAKE]

    # An absolute bound as well as a relative one: a grace of an hour would
    # satisfy "it eventually gives up" and still turn the light on by itself.
    assert 5.0 <= module.WAKE_GRACE_SECONDS <= 120.0
    clock[0] += module.WAKE_GRACE_SECONDS + 1
    assert runtime._take_pending() == []
    assert runtime._pending == [], "it was let go, not kept forever"


def test_the_hold_resets_once_the_strip_is_back(monkeypatch) -> None:
    """Otherwise the next wake would inherit the previous one's deadline and be
    dropped immediately."""
    import app.automation.runtime as module

    runtime = _Runtime2(connected=False)
    clock = [1000.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    runtime._pending.append(EVENT_WINDOWS_WAKE)
    runtime._take_pending()

    runtime.connected = True
    runtime._take_pending()
    assert runtime._held_wake_since is None

    runtime.connected = False
    clock[0] += 10_000
    runtime._pending.append(EVENT_WINDOWS_WAKE)
    runtime._take_pending()
    assert runtime._pending == [EVENT_WINDOWS_WAKE], "a new wake gets its own grace"

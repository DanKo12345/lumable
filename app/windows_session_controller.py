"""Listening for Windows locking, unlocking, sleeping and waking.

Its own native event filter and its own WTS registration, deliberately separate
from the hotkey controller's. Sharing one would make whichever component was
written first the owner of every native message in the app, and a bug in either
would then reach the other. Qt calls every installed filter in turn, and the
hotkey filter already returns "not mine" for anything that is not WM_HOTKEY, so
two of them cost nothing — measured, not assumed, before this was written.

Nothing here interprets what an event should *do*: it says what happened, and
the automation engine decides.
"""

from __future__ import annotations

from time import monotonic
from typing import Any

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from app.windows_session import (
    EVENT_LOCKED,
    EVENT_SLEEP,
    EVENT_UNLOCKED,
    EVENT_WAKE,
    SessionEvents,
)

# Notify only about the session this window lives in.
_NOTIFY_FOR_THIS_SESSION = 0


class WindowsSessionController(QObject, QAbstractNativeEventFilter):
    """Emits one signal per session event, at most once per event per moment."""

    locked = Signal()
    unlocked = Signal()
    slept = Signal()
    woke = Signal()
    # Everything, by name — the automation bridge listens here rather than to
    # four separate signals it would only fan back together.
    session_event = Signal(str)

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self._host = host
        self._events = SessionEvents()
        self._registered_hwnd: int | None = None
        self._installed = False

    def is_supported(self) -> bool:
        import sys

        return sys.platform == "win32"

    def start(self) -> bool:
        """Register for notifications. Safe to call twice; returns whether the
        app is now listening."""
        if not self.is_supported():
            return False
        if self._registered_hwnd is not None:
            return True
        hwnd = self._hwnd()
        if hwnd is None:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            ok = ctypes.windll.wtsapi32.WTSRegisterSessionNotification(
                wintypes.HWND(hwnd), _NOTIFY_FOR_THIS_SESSION
            )
        except (OSError, AttributeError, ValueError):
            return False
        if not ok:
            return False
        self._registered_hwnd = hwnd
        if not self._installed:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self)
                self._installed = True
        return True

    def stop(self) -> None:
        """Hand the registration back. Idempotent, and never raises — this runs
        on the way out, where an exception would take the shutdown with it."""
        # Forget what was heard while listening. The machine can lock and wake
        # any number of times before the next registration, and the first real
        # event afterwards must not be mistaken for a repeat of one we never saw.
        self._events.reset()
        hwnd, self._registered_hwnd = self._registered_hwnd, None
        if hwnd is not None:
            try:
                import ctypes
                from ctypes import wintypes

                ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(wintypes.HWND(hwnd))
            except (OSError, AttributeError, ValueError):
                pass
        if self._installed:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self)
            self._installed = False

    def _hwnd(self) -> int | None:
        try:
            return int(self._host.winId())
        except (TypeError, ValueError, RuntimeError, AttributeError):
            return None

    # ── event handling ───────────────────────────────────────────────
    def nativeEventFilter(self, event_type, message):
        # Always "not handled": these are broadcasts, and swallowing one would
        # take it from every other listener in the process, Qt's own included.
        if self._registered_hwnd is None:
            return False, 0
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            import ctypes
            from ctypes import wintypes

            msg = ctypes.cast(
                ctypes.c_void_p(int(message)), ctypes.POINTER(wintypes.MSG)
            ).contents
        except (ValueError, OSError, TypeError):
            return False, 0
        self.deliver(int(msg.message), int(msg.wParam))
        return False, 0

    def deliver(self, message: int, wparam: int, now: float | None = None) -> str | None:
        """Route one raw message. Public so the behaviour can be exercised
        without a machine that actually goes to sleep."""
        event = self._events.note(message, wparam, monotonic() if now is None else now)
        if event is None:
            return None
        {
            EVENT_LOCKED: self.locked,
            EVENT_UNLOCKED: self.unlocked,
            EVENT_SLEEP: self.slept,
            EVENT_WAKE: self.woke,
        }[event].emit()
        self.session_event.emit(event)
        return event

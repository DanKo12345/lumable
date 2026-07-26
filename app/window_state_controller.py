from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QApplication

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH

# A utility window: never reopen larger than this, even if a maximised size was
# saved previously.
STARTUP_MAX_WIDTH = 1440
STARTUP_MAX_HEIGHT = 960


class WindowStateHost(Protocol):
    _settings: dict

    def width(self) -> int: ...

    def height(self) -> int: ...

    def resize(self, width: int, height: int) -> None: ...

    def screen(self): ...

    def frameGeometry(self): ...

    def move(self, point) -> None: ...

    def winId(self): ...


class WindowStateController:
    def __init__(self, host: WindowStateHost) -> None:
        self._host = host

    def restore_startup_size(self) -> None:
        host = self._host
        screen = host.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        requested_width = int(host._settings.get("window_width", 1320))
        requested_height = int(host._settings.get("window_height", 860))
        # Sane ceiling so a previously-maximised (huge) saved size doesn't reopen
        # as a giant window with the content floating in empty space. This is a
        # utility, not a full-screen app.
        requested_width = min(requested_width, STARTUP_MAX_WIDTH)
        requested_height = min(requested_height, STARTUP_MAX_HEIGHT)
        if available is None:
            host.resize(max(WINDOW_MIN_WIDTH, requested_width), max(WINDOW_MIN_HEIGHT, requested_height))
            return

        # resize() sizes the *client* area, but the whole frameGeometry (client +
        # title bar + borders) must fit the work area. Reserve room for the frame
        # so the window never opens taller/wider than the screen. Below the
        # window minimum we cannot shrink further (setMinimumSize wins), so the
        # minimum itself is kept small enough to fit a 1366×768@150% work area.
        frame_w, frame_h = self._frame_overhead()
        max_width = max(WINDOW_MIN_WIDTH, available.width() - frame_w)
        max_height = max(WINDOW_MIN_HEIGHT, available.height() - frame_h)
        width = max(WINDOW_MIN_WIDTH, min(requested_width, max_width))
        height = max(WINDOW_MIN_HEIGHT, min(requested_height, max_height))
        host.resize(width, height)
        frame = host.frameGeometry()
        frame.moveCenter(available.center())
        if frame.left() < available.left():
            frame.moveLeft(available.left())
        if frame.top() < available.top():
            frame.moveTop(available.top())
        if frame.right() > available.right():
            frame.moveRight(available.right())
        if frame.bottom() > available.bottom():
            frame.moveBottom(available.bottom())
        host.move(frame.topLeft())

    def _frame_overhead(self) -> tuple[int, int]:
        """Best-effort size of the window decorations (title bar + borders).

        At startup the window isn't decorated yet, so frameGeometry equals the
        client geometry and the real overhead is unknown — fall back to a
        conservative allowance so the reserved space is never too small."""
        host = self._host
        frame = host.frameGeometry()
        over_w = max(0, frame.width() - host.width())
        over_h = max(0, frame.height() - host.height())
        # Never let a partially-known frame (e.g. 8×31 before the window is fully
        # decorated) shrink the reserve below the safe fallback.
        return max(over_w, 16), max(over_h, 48)

    def apply_windows_backdrop(self) -> None:
        # LumaBLE paints its own graphite + live-colour background through
        # AuroraBackground. Windows Mica/Acrylic is intentionally disabled here:
        # it adds an OS-controlled blue/grey material behind transparent widgets,
        # which makes the app look blue even when the selected strip colour is
        # green, orange, or neutral graphite.
        return

from __future__ import annotations

import ctypes
import sys
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
            host.resize(requested_width, requested_height)
            return

        width = max(WINDOW_MIN_WIDTH, min(requested_width, available.width()))
        height = max(WINDOW_MIN_HEIGHT, min(requested_height, available.height()))
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

    def apply_windows_backdrop(self) -> None:
        host = self._host
        if sys.platform != "win32":
            return
        if bool(host._settings.get("capture_compatibility", True)):
            return
        hwnd = int(host.winId())
        value = ctypes.c_int(2)
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError, ValueError, ctypes.ArgumentError):
            pass

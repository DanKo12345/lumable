from __future__ import annotations

import sys
from typing import Any

from PySide6.QtCore import QAbstractNativeEventFilter, QObject
from PySide6.QtWidgets import QApplication

from app.hotkeys import registrable
from app.quick_modes import QUICK_MODES

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
BRIGHTNESS_STEP = 8
_FIRST_HOTKEY_ID = 0xB000


class HotkeyController(QAbstractNativeEventFilter, QObject):
    """Registers OS-global hotkeys (Windows ``RegisterHotKey``) and dispatches
    them to host actions even when the app isn't focused — e.g. from a fullscreen
    game. No-op on non-Windows. Pure parsing lives in app.hotkeys; this is the
    thin OS glue, so it isn't unit-tested.

    Note: ``QAbstractNativeEventFilter`` MUST come first in the bases for PySide6 —
    with ``QObject`` first the filter is installed but never receives WM_HOTKEY.
    """

    def __init__(self, host: Any) -> None:
        QAbstractNativeEventFilter.__init__(self)
        QObject.__init__(self, host)
        self._host = host
        self._registered: dict[int, str] = {}  # RegisterHotKey id -> action
        self._failed: dict[str, str] = {}  # action -> the spec the system refused
        self._installed = False
        self._next_id = _FIRST_HOTKEY_ID

    def is_supported(self) -> bool:
        return sys.platform == "win32"

    # ── registration ─────────────────────────────────────────────────
    def apply(self, bindings: dict[str, str], *, enabled: bool) -> None:
        """Re-register the action→spec bindings, or clear them when disabled."""
        self.unregister_all()
        self._failed = {}
        if not enabled or not self.is_supported():
            return
        hwnd = self._hwnd()
        if hwnd is None:
            return
        import ctypes

        user32 = ctypes.windll.user32
        if not self._installed:
            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self)
                self._installed = True
        failures: list[tuple[str, str]] = []
        for action, spec, modifiers, vk in registrable(bindings):
            mods = modifiers | MOD_NOREPEAT
            hotkey_id = self._next_id
            self._next_id += 1
            if user32.RegisterHotKey(ctypes.c_void_p(hwnd), hotkey_id, mods, vk):
                self._registered[hotkey_id] = action
            else:
                failures.append((action, spec))
        self._failed = dict(failures)
        if failures:
            self._log_conflicts([spec for _action, spec in failures])

    def failed_bindings(self) -> dict[str, str]:
        """Actions whose combination the system refused, action -> spec.

        Kept so the panel can put the message beside the field it belongs to
        rather than in a log nobody reads, and so a conflict on one action says
        nothing about the others — which did register and do work.
        """
        return dict(self._failed)

    def _log_conflicts(self, specs: list[str]) -> None:
        host = self._host
        log = getattr(host, "_log", None)
        tr = getattr(host, "_tr", None)
        if not callable(log) or not callable(tr):
            return
        for spec in specs:
            log(tr("hotkeys.conflict_log", combo=spec))

    def unregister_all(self) -> None:
        if not self._registered:
            return
        if self.is_supported():
            import ctypes

            hwnd = self._hwnd()
            user32 = ctypes.windll.user32
            for hotkey_id in list(self._registered):
                if hwnd is not None:
                    user32.UnregisterHotKey(ctypes.c_void_p(hwnd), hotkey_id)
        self._registered.clear()

    def _hwnd(self) -> int | None:
        try:
            return int(self._host.winId())
        except (TypeError, ValueError, RuntimeError):
            return None

    # ── event handling ───────────────────────────────────────────────
    def nativeEventFilter(self, event_type, message):
        if not self._registered:
            return False, 0
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            import ctypes
            from ctypes import wintypes

            msg = ctypes.cast(ctypes.c_void_p(int(message)), ctypes.POINTER(wintypes.MSG)).contents
        except (ValueError, OSError, TypeError):
            return False, 0
        if msg.message == WM_HOTKEY:
            action = self._registered.get(int(msg.wParam))
            if action is not None:
                self._dispatch(action)
                return True, 0
        return False, 0

    def _dispatch(self, action: str) -> None:
        host = self._host
        try:
            if action == "toggle_power":
                host.power_button.setChecked(not host.power_button.isChecked())
                host._toggle_power()
            elif action == "brightness_up":
                self._nudge_brightness(BRIGHTNESS_STEP)
            elif action == "brightness_down":
                self._nudge_brightness(-BRIGHTNESS_STEP)
            elif action == "next_scene":
                self._cycle_scene(1)
            elif action == "prev_scene":
                self._cycle_scene(-1)
            elif action == "toggle_screen_sync":
                # Through the mode's own toggle, so the licence gate, the
                # connection check and stopping the other stream all stay in the
                # one place that already owns them.
                host._ambient_ui.toggle()
            elif action == "toggle_music":
                host._music_ui.toggle()
        except Exception:
            # A hotkey must never crash the app.
            pass

    def _nudge_brightness(self, delta: int) -> None:
        slider = self._host.brightness_slider
        slider.setValue(max(0, min(100, slider.value() + delta)))

    def _cycle_scene(self, direction: int) -> None:
        keys = [mode.key for mode in QUICK_MODES]
        if not keys:
            return
        current = getattr(self._host, "_active_mode_key", None)
        index = keys.index(current) if current in keys else -1
        self._host._activate_quick_mode(keys[(index + direction) % len(keys)])

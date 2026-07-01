from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit

from app.hotkeys import Hotkey, format_hotkey

# Qt key -> our normalized named-key token.
_QT_NAMED = {
    Qt.Key_Up: "UP", Qt.Key_Down: "DOWN", Qt.Key_Left: "LEFT", Qt.Key_Right: "RIGHT",
    Qt.Key_Space: "SPACE", Qt.Key_Home: "HOME", Qt.Key_End: "END",
    Qt.Key_PageUp: "PAGEUP", Qt.Key_PageDown: "PAGEDOWN",
    Qt.Key_Insert: "INSERT", Qt.Key_Delete: "DELETE",
}
_MOD_KEYS = {Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_AltGr}


class HotkeyCaptureEdit(QLineEdit):
    """A read-only field that records the key combo you press (e.g. Ctrl+Alt+F1)
    instead of making you type its name. Emits ``captured`` once a full combo
    (modifier + key) is pressed; Esc clears it."""

    captured = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def _key_token(self, key: int) -> str | None:
        if Qt.Key_A <= key <= Qt.Key_Z:
            return chr(key)  # Qt.Key_A == ord('A')
        if Qt.Key_0 <= key <= Qt.Key_9:
            return chr(key)
        if Qt.Key_F1 <= key <= Qt.Key_F12:
            return f"F{key - Qt.Key_F1 + 1}"
        return _QT_NAMED.get(key)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.clear()
            self.captured.emit()
            return
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            super().keyPressEvent(event)  # let Tab move focus out of the field
            return
        if key in _MOD_KEYS:
            return  # wait for the real key while modifiers are held
        token = self._key_token(key)
        if token is None:
            return
        # Capture exactly what's pressed — a single key or a combo. (A bare key
        # registers globally, which is the user's choice; defaults use modifiers.)
        mods: set[str] = set()
        modifiers = event.modifiers()
        if modifiers & Qt.ControlModifier:
            mods.add("ctrl")
        if modifiers & Qt.AltModifier:
            mods.add("alt")
        if modifiers & Qt.ShiftModifier:
            mods.add("shift")
        if modifiers & Qt.MetaModifier:
            mods.add("win")
        self.setText(format_hotkey(Hotkey(frozenset(mods), token)))
        self.captured.emit()

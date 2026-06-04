from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

from app.quick_modes import QUICK_MODES


class ShortcutController:
    def __init__(self, host: Any) -> None:
        self._host = host
        self._shortcuts: list[QShortcut] = []

    @property
    def shortcuts(self) -> list[QShortcut]:
        return self._shortcuts

    def wire(self) -> None:
        power_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self._host)
        power_shortcut.setContext(Qt.WindowShortcut)
        power_shortcut.activated.connect(self.handle_power)
        self._shortcuts.append(power_shortcut)

        for index, mode in enumerate(QUICK_MODES[:5], start=1):
            shortcut = QShortcut(QKeySequence(getattr(Qt, f"Key_{index}")), self._host)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(lambda key=mode.key: self.handle_quick_mode(key))
            self._shortcuts.append(shortcut)

    def accepts_action(self) -> bool:
        if QApplication.activeModalWidget() is not None:
            return False
        focus = QApplication.focusWidget()
        if focus is None:
            return True
        return not isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox))

    def handle_power(self) -> None:
        if not self.accepts_action():
            return
        self._host.power_button.setChecked(not self._host.power_button.isChecked())
        self._host._toggle_power()

    def handle_quick_mode(self, mode_key: str) -> None:
        if not self.accepts_action():
            return
        self._host._activate_quick_mode(mode_key)

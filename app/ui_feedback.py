from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from app.localization import localization_manager
from app.widgets import LiquidButton


class UiFeedback:
    def __init__(
        self,
        parent: QWidget,
        log_output: QTextEdit,
        theme_provider: Callable[[], dict[str, str]],
        translate: Callable[[str], str],
    ) -> None:
        self._parent = parent
        self._log_output = log_output
        self._theme_provider = theme_provider
        self._translate = translate
        self._raw_log_messages: list[str] = []

    def show_error(self, message: str) -> None:
        theme = self._theme_provider()
        message = localization_manager.normalize_error_message(message)
        dialog = QDialog(self._parent)
        dialog.setWindowTitle(self._translate("dialog.title"))
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        dialog.setStyleSheet(
            f"""
            QDialog {{
                background: {theme["surface_strong"]};
            }}
            QLabel {{
                color: {theme["text"]};
                background: transparent;
                min-width: 420px;
                font-size: 13px;
            }}
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 16, 26, 12)
        layout.setSpacing(16)

        label = QLabel(message, dialog)
        label.setTextFormat(Qt.PlainText)
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumWidth(420)
        label.setMaximumWidth(420)
        layout.addWidget(label)

        ok_button = LiquidButton(self._translate("dialog.ok"), role="ghost", parent=dialog)
        ok_button.setFixedSize(104, 56)
        ok_button.clicked.connect(dialog.accept)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addStretch(1)
        button_row.addWidget(ok_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        dialog.adjustSize()
        dialog.exec()

    def log(self, message: str) -> None:
        self._raw_log_messages.append(message)
        self.refresh_logs()

    def refresh_logs(self) -> None:
        lines = [
            localization_manager.normalize_status_message(message)
            for message in self._raw_log_messages
        ]
        self._log_output.setPlainText("\n".join(lines))

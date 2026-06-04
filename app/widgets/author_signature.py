from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class AuthorSignatureMark(QWidget):
    clicked = Signal()

    def __init__(self, theme_provider: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_provider = theme_provider
        self.setObjectName("heroSignature")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(64)
        self.setMinimumHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        self.edition_label = QLabel()
        self.edition_label.setObjectName("authorEditionText")
        self.edition_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.edition_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(self.edition_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addStretch(1)
        self.refresh_text()

    def sizeHint(self) -> QSize:
        return QSize(64, 40)

    def refresh_text(self) -> None:
        self.refresh_theme()

    def set_edition(self, text: str, tooltip: str = "") -> None:
        clean_text = str(text).strip()
        self.edition_label.setText(clean_text)
        self.edition_label.setToolTip(tooltip)
        self.setToolTip(tooltip)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        from app.feature_gate import is_pro
        from app.theme import theme_manager

        tokens = self._theme_provider()
        pro_enabled = is_pro()
        if pro_enabled:
            color = "#f0c060" if theme_manager.is_dark else "#c07010"
        else:
            color = tokens.get("muted", "rgba(255,255,255,0.58)")
        weight = "600" if pro_enabled else "400"
        self.edition_label.setStyleSheet(f"background: transparent; color: {color}; font-weight: {weight};")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

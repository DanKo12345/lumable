from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QEventLoop, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton


class _LicensePanel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(560, 360)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if theme_manager.is_dark:
            fill.setColorAt(0.0, QColor(43, 60, 108, 248))
            fill.setColorAt(1.0, QColor(15, 22, 52, 252))
        else:
            fill.setColorAt(0.0, QColor(250, 252, 255, 252))
            fill.setColorAt(1.0, QColor(222, 235, 255, 252))
        painter.fillPath(path, fill)

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        shine.setColorAt(0.0, QColor(255, 255, 255, 30 if theme_manager.is_dark else 62))
        shine.setColorAt(0.48, QColor(255, 255, 255, 6 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(98 if theme_manager.is_dark else 110)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class LicenseOverlay(QWidget):
    def __init__(
        self,
        labels: dict[str, str],
        activate_callback: Callable[[str], tuple[bool, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._activate_callback = activate_callback
        self._loop: QEventLoop | None = None
        self._accepted = False
        self._fade_anim: QPropertyAnimation | None = None
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _LicensePanel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(30, 28, 30, 24)
        panel_layout.setSpacing(14)

        title = QLabel(labels["title"], self._panel)
        title.setObjectName("licenseTitle")
        title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        subtitle = QLabel(labels["subtitle"], self._panel)
        subtitle.setObjectName("licenseSubtitle")
        subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        subtitle.setWordWrap(True)
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)

        field_box = QFrame(self._panel)
        field_box.setObjectName("licenseFieldBox")
        field_layout = QVBoxLayout(field_box)
        field_layout.setContentsMargins(16, 12, 16, 12)
        field_layout.setSpacing(8)
        field_label = QLabel(labels["key_label"], field_box)
        field_label.setObjectName("licenseFieldLabel")
        self.key_input = QLineEdit(field_box)
        self.key_input.setObjectName("licenseKeyInput")
        self.key_input.setPlaceholderText(labels["placeholder"])
        self.key_input.returnPressed.connect(self._activate)
        field_layout.addWidget(field_label)
        field_layout.addWidget(self.key_input)
        panel_layout.addWidget(field_box)

        self.message_label = QLabel("", self._panel)
        self.message_label.setObjectName("licenseMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumHeight(30)
        panel_layout.addWidget(self.message_label)
        panel_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.buy_button = LiquidButton(labels["buy"], "accent_soft", self._panel)
        self.buy_button.setMinimumSize(142, 40)
        self.buy_button.clicked.connect(self._show_buy_message)
        cancel_button = LiquidButton(labels["cancel"], "ghost", self._panel)
        cancel_button.setMinimumSize(122, 40)
        cancel_button.clicked.connect(self.close_overlay)
        activate_button = LiquidButton(labels["activate"], "accent_soft", self._panel)
        activate_button.setMinimumSize(150, 40)
        activate_button.clicked.connect(self._activate)
        buttons.addStretch(1)
        buttons.addWidget(self.buy_button)
        buttons.addWidget(cancel_button)
        buttons.addWidget(activate_button)
        buttons.addStretch(1)
        panel_layout.addLayout(buttons)

    def exec(self) -> bool:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self._prepare_open_animation()
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self.key_input.setFocus(Qt.PopupFocusReason)
        QTimer.singleShot(0, self._start_open_animation)
        self._loop = QEventLoop(self)
        self._loop.exec()
        return self._accepted

    def _activate(self) -> None:
        ok, message = self._activate_callback(self.key_input.text())
        self.message_label.setText(message)
        self.message_label.setProperty("state", "success" if ok else "error")
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)
        if ok:
            self._accepted = True
            self.close_overlay()

    def _show_buy_message(self) -> None:
        self.message_label.setText(self._labels["buy_unavailable"])
        self.message_label.setProperty("state", "info")
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)

    def _prepare_open_animation(self) -> None:
        self.layout().activate()
        self._opacity_effect.setOpacity(0.0)

    def _start_open_animation(self) -> None:
        if not self.isVisible():
            return
        self.layout().activate()
        self._panel.raise_()

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(190)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_anim.start()

    def close_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 44 if theme_manager.is_dark else 26))
        painter.drawRect(self.rect())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
        return super().eventFilter(watched, event)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            #licenseTitle {{
                color: {palette["text"]};
                font-size: 22px;
                font-weight: 800;
            }}
            #licenseSubtitle {{
                color: {palette["text_soft"]};
                font-size: 12px;
                font-weight: 500;
                line-height: 1.35em;
            }}
            #licenseFieldBox {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 16px;
            }}
            #licenseFieldLabel {{
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 800;
            }}
            #licenseKeyInput {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 14px;
                color: {palette["text"]};
                padding: 0 14px;
                min-height: 40px;
                font-size: 13px;
                font-weight: 700;
            }}
            #licenseMessage {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 600;
            }}
            #licenseMessage[state="error"] {{
                color: #ff9aa9;
            }}
            #licenseMessage[state="success"] {{
                color: #83f0c9;
            }}
            """
        )

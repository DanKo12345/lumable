from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton


class _Panel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(580, 432)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if theme_manager.is_dark:
            fill.setColorAt(0.0, QColor(34, 38, 50, 250))
            fill.setColorAt(1.0, QColor(18, 20, 28, 252))
        else:
            fill.setColorAt(0.0, QColor(250, 252, 255, 252))
            fill.setColorAt(1.0, QColor(222, 235, 255, 252))
        painter.fillPath(path, fill)
        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(92 if theme_manager.is_dark else 104)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class ApiConnectOverlay(QWidget):
    """A short 'How to connect' window: copy a ready Home Assistant config, a
    ready curl example, and an honest 'later' note for Stream Deck."""

    copyHomeAssistant = Signal()
    copyCurl = Signal()
    closed = Signal()

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _Panel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(30, 26, 30, 22)
        panel_layout.setSpacing(8)

        title = QLabel(labels["title"], self._panel)
        title.setObjectName("aboutTitle")
        panel_layout.addWidget(title)

        panel_layout.addWidget(
            self._section(labels["ha_title"], labels["ha_desc"], labels["ha_copy"], self.copyHomeAssistant.emit)
        )
        panel_layout.addWidget(
            self._section(labels["scripts_title"], labels["scripts_desc"], labels["scripts_copy"], self.copyCurl.emit)
        )
        panel_layout.addWidget(self._section(labels["sd_title"], labels["sd_desc"], None, None))

        ok_row = QHBoxLayout()
        ok_row.setContentsMargins(0, 6, 0, 0)
        ok_row.addStretch(1)
        ok_button = LiquidButton(labels["ok"], "accent_soft", self._panel)
        ok_button.setFixedSize(104, 36)
        ok_button.clicked.connect(self.close_overlay)
        ok_row.addWidget(ok_button)
        panel_layout.addLayout(ok_row)

    def _section(self, title_text: str, body_text: str, button_text: str | None, on_click) -> QFrame:
        section = QFrame(self._panel)
        section.setObjectName("apiConnectSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(4)
        title = QLabel(title_text, section)
        title.setObjectName("apiConnectSectionTitle")
        body = QLabel(body_text, section)
        body.setObjectName("apiConnectBody")
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body)
        if button_text is not None and on_click is not None:
            button = LiquidButton(button_text, "ghost", section)
            button.setFixedSize(178, 34)
            button.clicked.connect(lambda: on_click())
            layout.addWidget(button, 0, Qt.AlignLeft)
        return section

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self.layout().activate()
        end_pos = self._panel.pos()
        self._panel.move(end_pos + QPoint(0, 14))
        self._opacity_effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(170)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim = QPropertyAnimation(self._panel, b"pos", self)
        self._panel_anim.setDuration(210)
        self._panel_anim.setStartValue(end_pos + QPoint(0, 14))
        self._panel_anim.setEndValue(end_pos)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()
        self._panel_anim.start()

    def close_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.closed.emit()
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
            #aboutTitle {{ color: {palette["text"]}; font-size: 20px; font-weight: 800; }}
            #apiConnectSection {{
                background: transparent;
                border-bottom: 1px solid {palette["field_border"]};
            }}
            #apiConnectSectionTitle {{ color: {palette["text"]}; font-size: 13px; font-weight: 700; }}
            #apiConnectBody {{ color: {palette["text_soft"]}; font-size: 12px; font-weight: 500; }}
            """
        )

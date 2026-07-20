from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.theme import overlay_panel_colors, qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton


class _Panel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(472, 306)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        panel_top, panel_bottom = overlay_panel_colors()
        fill.setColorAt(0.0, panel_top)
        fill.setColorAt(1.0, panel_bottom)
        painter.fillPath(path, fill)
        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(98 if theme_manager.is_dark else 110)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class _WarningMark(QWidget):
    """Small vector warning sign, crisp at every DPI without an emoji glyph."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(42, 38)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        triangle = QPainterPath()
        triangle.moveTo(21, 2)
        triangle.lineTo(40, 35)
        triangle.quadTo(40.7, 37, 38, 37)
        triangle.lineTo(4, 37)
        triangle.quadTo(1.3, 37, 2, 35)
        triangle.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(244, 187, 94))
        painter.drawPath(triangle)
        painter.setPen(QPen(QColor(44, 35, 20), 3.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(21, 12, 21, 24)
        painter.setBrush(QColor(44, 35, 20))
        painter.drawEllipse(QRectF(19.4, 29, 3.2, 3.2))


class LanAccessOverlay(QWidget):
    """Asks for deliberate consent before exposing the API on the LAN."""

    accepted = Signal()
    closed = Signal()

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
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
        panel_layout.setContentsMargins(32, 22, 32, 22)
        panel_layout.setSpacing(8)

        panel_layout.addWidget(_WarningMark(self._panel), 0, Qt.AlignHCenter)

        title = QLabel(labels["title"], self._panel)
        title.setObjectName("lanTitle")
        title.setAlignment(Qt.AlignHCenter)
        panel_layout.addWidget(title)

        body = QLabel(labels["body"], self._panel)
        body.setObjectName("lanBody")
        body.setAlignment(Qt.AlignHCenter)
        body.setWordWrap(True)
        panel_layout.addWidget(body)

        note = QLabel(labels["note"], self._panel)
        note.setObjectName("lanNote")
        note.setAlignment(Qt.AlignHCenter)
        note.setWordWrap(True)
        panel_layout.addWidget(note)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(40, 4, 40, 0)
        buttons.setSpacing(10)
        cancel = LiquidButton(labels["cancel"], "ghost", self._panel)
        cancel.setFixedSize(170, 40)
        cancel.clicked.connect(self.close_overlay)
        allow = LiquidButton(labels["allow"], "accent", self._panel)
        allow.setFixedSize(170, 40)
        allow.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(allow)
        panel_layout.addLayout(buttons)

    def _accept(self) -> None:
        self.accepted.emit()
        self.close_overlay()

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
        painter.setBrush(QColor(0, 0, 0, 48 if theme_manager.is_dark else 28))
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
            #lanTitle {{ color: {palette["text"]}; font-size: 20px; font-weight: 800; }}
            #lanBody {{ color: {palette["text_soft"]}; font-size: 13px; font-weight: 500; }}
            #lanNote {{
                color: {palette["text_soft"]}; font-size: 11px; font-weight: 600;
                background: {palette["field_alt"]}; border: 1px solid {palette["field_border"]};
                border-radius: 10px; padding: 9px 12px;
            }}
            """
        )

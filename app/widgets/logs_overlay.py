from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton


class _LogsPanel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(680, 480)
        self.setMaximumSize(860, 640)

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

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        shine.setColorAt(0.0, QColor(255, 255, 255, 24 if theme_manager.is_dark else 54))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(92 if theme_manager.is_dark else 112)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class LogsOverlay(QWidget):
    closed = Signal()

    def __init__(self, labels: dict[str, str], text: str, parent: QWidget | None = None) -> None:
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
        self._panel = _LogsPanel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(24, 22, 24, 22)
        panel_layout.setSpacing(10)

        title = QLabel(labels["title"], self._panel)
        title.setObjectName("logsOverlayTitle")
        title.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(title)

        subtitle = QLabel(labels["subtitle"], self._panel)
        subtitle.setObjectName("logsOverlaySubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        panel_layout.addWidget(subtitle)
        panel_layout.addSpacing(4)

        self.log_output = QTextEdit(self._panel)
        self.log_output.setObjectName("overlayLogOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setPlainText(text or labels["empty"])
        self.log_output.verticalScrollBar().setSingleStep(18)
        panel_layout.addWidget(self.log_output, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = LiquidButton(labels["close"], "accent_soft", self._panel)
        close_button.setFixedSize(100, 38)
        close_button.clicked.connect(self.close_overlay)
        button_row.addWidget(close_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        panel_layout.addLayout(button_row)

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()

    def _start_open_animation(self) -> None:
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
            #overlayLogOutput {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 16px;
                color: {palette["text"]};
                padding: 14px;
                font-family: Consolas, 'Cascadia Mono', monospace;
                font-size: 12px;
                font-weight: 500;
            }}
            #logsOverlayTitle {{
                color: {palette["text"]};
                font-size: 20px;
                font-weight: 800;
                background: transparent;
            }}
            #logsOverlaySubtitle {{
                color: {palette["muted"]};
                font-size: 11px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

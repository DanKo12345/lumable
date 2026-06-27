from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton


class _UpdatePanel(QFrame):
    RADIUS = 22.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(460)

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
        shine.setColorAt(0.0, QColor(255, 255, 255, 26 if theme_manager.is_dark else 58))
        shine.setColorAt(0.42, QColor(255, 255, 255, 5 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        # Soft accent glow strip along the top — quiet "something new" cue.
        accent = qcolor_from_token(theme_manager.palette["accent_start"])
        glow = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.5)
        glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 40))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.fillPath(path, glow)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(92 if theme_manager.is_dark else 104)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class _UpdateBadge(QWidget):
    """A small accent download glyph shown beside the title, matching the
    emblem treatment of the License/About windows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(40, 40)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        start = qcolor_from_token(theme_manager.palette["accent_start"])
        end = qcolor_from_token(theme_manager.palette["accent_end"])

        glow_radius = 20.0
        glow = QRadialGradient(cx, cy, glow_radius)
        glow.setColorAt(0.0, QColor(start.red(), start.green(), start.blue(), 130))
        glow.setColorAt(0.6, QColor(start.red(), start.green(), start.blue(), 40))
        glow.setColorAt(1.0, QColor(start.red(), start.green(), start.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        radius = 15.0
        fill = QLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
        fill.setColorAt(0.0, start)
        fill.setColorAt(1.0, end)
        painter.setBrush(fill)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        pen = QPen(QColor(255, 255, 255), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        # Download glyph: a downward arrow over a short tray line.
        painter.drawLine(QPointF(cx, cy - 6.0), QPointF(cx, cy + 3.5))
        head = QPainterPath()
        head.moveTo(cx - 4.5, cy - 0.5)
        head.lineTo(cx, cy + 4.5)
        head.lineTo(cx + 4.5, cy - 0.5)
        painter.drawPath(head)
        painter.drawLine(QPointF(cx - 5.5, cy + 8.0), QPointF(cx + 5.5, cy + 8.0))


class UpdateOverlay(QWidget):
    """Quiet, modern 'update available' pop-up shown at most once per version."""

    update_requested = Signal()
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
        self._panel = _UpdatePanel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(26, 24, 26, 22)
        panel_layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(_UpdateBadge(self._panel), 0, Qt.AlignVCenter)
        title = QLabel(labels["title"], self._panel)
        title.setObjectName("updateTitle")
        header.addWidget(title, 0, Qt.AlignVCenter)
        header.addStretch(1)
        panel_layout.addLayout(header)

        body = QLabel(labels["body"], self._panel)
        body.setObjectName("updateBody")
        body.setWordWrap(True)
        panel_layout.addWidget(body)

        panel_layout.addSpacing(6)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        later_button = LiquidButton(labels["later"], "ghost", self._panel)
        later_button.setFixedSize(120, 40)
        later_button.clicked.connect(self.close_overlay)
        update_button = LiquidButton(labels["update"], "accent_soft", self._panel)
        update_button.setFixedSize(150, 40)
        update_button.clicked.connect(self._on_update)
        buttons.addWidget(later_button, 0, Qt.AlignVCenter)
        buttons.addWidget(update_button, 0, Qt.AlignVCenter)
        panel_layout.addLayout(buttons)

    def _on_update(self) -> None:
        self.update_requested.emit()
        self.close_overlay()

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
            #updateTitle {{
                color: {palette["text"]};
                font-size: 19px;
                font-weight: 800;
            }}
            #updateBody {{
                color: {palette["text_soft"]};
                font-size: 13px;
                font-weight: 500;
                line-height: 1.4em;
            }}
            """
        )

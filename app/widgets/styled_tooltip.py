from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager


class _TooltipBubble(QWidget):
    """A frameless, themed replacement for the native tooltip popup."""

    RADIUS = 9.0
    MAX_WIDTH = 300

    def __init__(self) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 8, 11, 9)
        self._label = QLabel(self)
        self._label.setObjectName("styledTooltipLabel")
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(self.MAX_WIDTH)
        layout.addWidget(self._label)

    def show_text(self, text: str, global_pos: QPoint) -> None:
        text_color = qcolor_from_token(theme_manager.palette["text"]).name()
        self._label.setStyleSheet(
            f"background: transparent; color: {text_color}; font-size: 12px; font-weight: 500;"
        )
        self._label.setText(text)
        self.adjustSize()
        self._move_within_screen(global_pos)
        self.show()
        self.raise_()

    def _move_within_screen(self, global_pos: QPoint) -> None:
        pos = global_pos + QPoint(14, 18)
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 4, min(pos.x(), area.right() - self.width() - 4))
            y = pos.y()
            if y + self.height() > area.bottom() - 4:
                y = global_pos.y() - self.height() - 12
            y = max(area.top() + 4, y)
            pos = QPoint(x, y)
        self.move(pos)

    def paintEvent(self, event) -> None:
        palette = theme_manager.palette
        bg = qcolor_from_token(palette["surface_strong"])
        bg.setAlpha(255)
        border = qcolor_from_token(palette["surface_border"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.fillPath(path, bg)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class TooltipManager(QObject):
    """Application-wide event filter that swaps native tooltips for themed ones.

    Install it on the QApplication. It consumes ``ToolTip`` events (so the OS
    tooltip never appears) and shows a styled bubble instead, which respects the
    current light/dark theme — unlike QSS/palette, which the Windows 11 style
    ignores for tooltip popups.
    """

    _HIDE_EVENTS = frozenset(
        {
            QEvent.Type.Leave,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Wheel,
            QEvent.Type.WindowDeactivate,
            QEvent.Type.FocusOut,
        }
    )

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bubble = _TooltipBubble()
        self._shutdown = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(8000)
        self._hide_timer.timeout.connect(self._bubble.hide)

    def shutdown(self) -> None:
        """Remove the top-level tooltip bubble before the owning window dies."""
        if self._shutdown:
            return
        self._shutdown = True
        self._hide_timer.stop()
        self._bubble.hide()
        self._bubble.close()
        self._bubble.deleteLater()

    def eventFilter(self, obj, event) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.ToolTip:
            global_pos = event.globalPos()
            text = obj.toolTip() if isinstance(obj, QWidget) else ""
            if not text:
                under = QApplication.widgetAt(global_pos)
                if isinstance(under, QWidget):
                    text = under.toolTip()
            if text:
                self._bubble.show_text(text, global_pos)
                self._hide_timer.start()
                return True
            self._bubble.hide()
        elif event_type in self._HIDE_EVENTS:
            self._bubble.hide()
        return False

from __future__ import annotations

from PySide6.QtCore import Property, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QPushButton

from app.theme import theme_manager
from app.widgets.animation_helpers import ButtonAnimationMixin


class ThemeToggleButton(ButtonAnimationMixin, QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(140, 40)
        self.setFlat(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._scale = 1.0
        self._ripple = 0.0
        self._ripple_opacity = 0.0
        self._ripple_x = 0.0
        self._ripple_y = 0.0
        self._init_button_motion()

    def get_scale(self):
        return self._scale

    def set_scale(self, value):
        self._scale = float(value)
        self.update()

    scaleValue = Property(float, get_scale, set_scale)

    def get_ripple(self):
        return self._ripple

    def set_ripple(self, value):
        self._ripple = float(value)
        self._ripple_opacity = max(0.0, 1.0 - self._ripple)
        self.update()

    rippleValue = Property(float, get_ripple, set_ripple)

    def enterEvent(self, event):
        self._handle_button_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._handle_button_leave()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pos = event.position()
        self._handle_button_press(pos.x(), pos.y())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._handle_button_release()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        grow = max(0.0, self._scale - 1.0)
        inset = max(0.8, 4.0 - grow * 75.0)
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)

        radius = 18.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        palette = theme_manager.palette

        top = QColor(255, 255, 255, 30 if theme_manager.is_dark else 188)
        bottom = QColor(160, 190, 255, 18 if theme_manager.is_dark else 138)
        fill = QLinearGradient(0, 0, 0, rect.height())
        fill.setColorAt(0.0, top)
        fill.setColorAt(1.0, bottom)
        painter.fillPath(path, fill)

        shine = QLinearGradient(0, 0, 0, rect.height() * 0.55)
        shine.setColorAt(0.0, QColor(255, 255, 255, 88 if theme_manager.is_dark else 96))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        if self._ripple_opacity > 0.01:
            ripple_radius = 8 + self._ripple * max(rect.width(), rect.height()) * 0.9
            ripple = QRadialGradient(self._ripple_x, self._ripple_y, ripple_radius)
            ripple.setColorAt(0.0, QColor(255, 255, 255, int(72 * self._ripple_opacity)))
            ripple.setColorAt(0.45, QColor(210, 228, 255, int(32 * self._ripple_opacity)))
            ripple.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), ripple)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 38 if theme_manager.is_dark else 144), 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        painter.setPen(QColor(palette["text"]))
        font = self.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.text())

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, Property, QRectF, QSequentialAnimationGroup, Qt, QPropertyAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSlider

from app.theme import qcolor_from_token, theme_manager


class LiquidSlider(QSlider):
    def __init__(self, accent="neutral", parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumHeight(68)
        self.accent = accent
        self._hover = 0.0
        self._press = 0.0
        self._impact = 0.0
        self._display_value = float(self.value())

        self._hover_anim = QPropertyAnimation(self, b"hoverValue", self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._press_anim = QPropertyAnimation(self, b"pressValue", self)
        self._press_anim.setDuration(120)
        self._press_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._landing_group = QSequentialAnimationGroup(self)
        self._landing_stage_1 = QPropertyAnimation(self, b"pressValue", self)
        self._landing_stage_1.setDuration(26)
        self._landing_stage_1.setEasingCurve(QEasingCurve.OutCubic)
        self._landing_stage_2 = QPropertyAnimation(self, b"pressValue", self)
        self._landing_stage_2.setDuration(86)
        self._landing_stage_2.setEasingCurve(QEasingCurve.OutCubic)
        self._landing_group.addAnimation(self._landing_stage_1)
        self._landing_group.addAnimation(self._landing_stage_2)

        self._wheel_group = QSequentialAnimationGroup(self)
        self._wheel_stage_1 = QPropertyAnimation(self, b"pressValue", self)
        self._wheel_stage_1.setDuration(44)
        self._wheel_stage_1.setEasingCurve(QEasingCurve.OutCubic)
        self._wheel_stage_2 = QPropertyAnimation(self, b"pressValue", self)
        self._wheel_stage_2.setDuration(118)
        self._wheel_stage_2.setEasingCurve(QEasingCurve.OutCubic)
        self._wheel_group.addAnimation(self._wheel_stage_1)
        self._wheel_group.addAnimation(self._wheel_stage_2)

        self._impact_anim = QPropertyAnimation(self, b"impactValue", self)
        self._impact_anim.setDuration(180)
        self._impact_anim.setEasingCurve(QEasingCurve.Linear)

        self._display_anim = QPropertyAnimation(self, b"displayValue", self)
        self._display_anim.setDuration(135)
        self._display_anim.setEasingCurve(QEasingCurve.OutQuad)

        self.valueChanged.connect(self._animate_display_value)

    def set_accent_color(self, accent: str):
        self.accent = accent
        self.update()

    def _accent_color(self) -> QColor:
        palette = {
            "red": QColor("#ff7d86"),
            "green": QColor("#55d2a4"),
            "blue": QColor("#76a9ff"),
            "yellow": QColor("#e7c563"),
            "purple": QColor("#b58fff"),
            "neutral": QColor("#8fbfff"),
        }
        return QColor(palette.get(self.accent, palette["neutral"]))

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._press_in()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._press_out()

    def wheelEvent(self, event):
        if not self.underMouse() or not self.isEnabled():
            event.ignore()
            return

        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        step_size = self.singleStep() or 1
        steps = round(delta / 120)
        if steps == 0:
            event.accept()
            return

        new_value = self.value() + steps * step_size
        new_value = max(self.minimum(), min(self.maximum(), new_value))
        if new_value == self.value():
            event.accept()
            return

        self._wheel_group.stop()
        self._landing_group.stop()
        self._press_anim.stop()
        self._impact_anim.stop()
        self._impact = 0.0
        self._wheel_stage_1.setStartValue(self._press)
        self._wheel_stage_1.setEndValue(0.18)
        self._wheel_stage_2.setStartValue(0.18)
        self._wheel_stage_2.setEndValue(0.0)
        self._wheel_group.start()
        self.setValue(new_value)
        event.accept()

    def _press_in(self):
        self._wheel_group.stop()
        self._landing_group.stop()
        self._impact_anim.stop()
        self._impact = 0.0
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(1.0)
        self._press_anim.start()

    def _press_out(self):
        self._press_anim.stop()
        self._wheel_group.stop()
        self._landing_group.stop()
        self._landing_stage_1.setStartValue(self._press)
        self._landing_stage_1.setEndValue(0.16)
        self._landing_stage_2.setStartValue(0.16)
        self._landing_stage_2.setEndValue(0.0)
        self._landing_group.start()
        self._impact_anim.stop()
        self._impact_anim.setStartValue(1.0)
        self._impact_anim.setEndValue(0.0)
        self._impact_anim.start()

    def _animate_display_value(self, value: int):
        if self.isSliderDown():
            self._display_anim.stop()
            self._display_value = float(value)
            self.update()
            return
        self._display_anim.stop()
        self._display_anim.setStartValue(self._display_value)
        self._display_anim.setEndValue(float(value))
        self._display_anim.start()

    def get_hover_value(self):
        return self._hover

    def set_hover_value(self, value):
        self._hover = float(value)
        self.update()

    hoverValue = Property(float, get_hover_value, set_hover_value)

    def get_press_value(self):
        return self._press

    def set_press_value(self, value):
        self._press = float(value)
        self.update()

    pressValue = Property(float, get_press_value, set_press_value)

    def get_impact_value(self):
        return self._impact

    def set_impact_value(self, value):
        self._impact = float(value)
        self.update()

    impactValue = Property(float, get_impact_value, set_impact_value)

    def get_display_value(self):
        return self._display_value

    def set_display_value(self, value):
        self._display_value = float(value)
        self.update()

    displayValue = Property(float, get_display_value, set_display_value)

    def _ratio_from_value(self, value: float) -> float:
        span = self.maximum() - self.minimum()
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (value - self.minimum()) / span))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        accent = self._accent_color()
        palette = theme_manager.palette
        groove_color = qcolor_from_token(palette["surface_line"])
        handle_fill = QColor(255, 255, 255, 245)
        handle_border = QColor(255, 255, 255, 90) if theme_manager.is_dark else QColor(80, 130, 210, 90)

        left = 14.0
        right = self.width() - 14.0
        cy = self.height() / 2 + 3.0
        groove_h = 7.2 + self._hover * 0.8 + self._press * 0.55
        groove_rect = QRectF(left, cy - groove_h / 2, max(12.0, right - left), groove_h)

        ratio = self._ratio_from_value(self._display_value)
        fill_width = groove_rect.width() * ratio
        fill_rect = QRectF(groove_rect.left(), groove_rect.top(), fill_width, groove_rect.height())
        handle_x = groove_rect.left() + fill_width
        handle_x = max(groove_rect.left(), min(groove_rect.right(), handle_x))

        impact_phase = 1.0 - self._impact
        landing_drop = 0.0
        shake_x = 0.0
        shake_y = 0.0
        if self._impact > 0.001:
            landing_drop = math.sin(min(1.0, impact_phase * 1.65) * math.pi) * (self._impact ** 0.25) * 4.4
            shake_x = math.sin(impact_phase * 32.0) * (self._impact ** 1.1) * 1.6
            shake_y = math.sin(impact_phase * 24.0) * (self._impact ** 1.25) * 0.65
            handle_x += shake_x

        handle_radius = 9.3 + self._hover * 1.5 + self._press * 2.7 + self._impact * 0.45
        handle_cy = cy - self._press * 1.6 + landing_drop + shake_y

        glow_radius = 18.0 + self._hover * 6.5 + self._press * 7.5 + self._impact * 3.2
        glow = QRadialGradient(handle_x, handle_cy, glow_radius)
        glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 96 if theme_manager.is_dark else 64))
        glow.setColorAt(0.50, QColor(accent.red(), accent.green(), accent.blue(), 34 if theme_manager.is_dark else 22))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        glow_rect = QRectF(handle_x - glow_radius, handle_cy - glow_radius, glow_radius * 2, glow_radius * 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(glow_rect)

        painter.setPen(Qt.NoPen)
        painter.setBrush(groove_color)
        painter.drawRoundedRect(groove_rect, groove_rect.height() / 2, groove_rect.height() / 2)

        if fill_rect.width() > 0:
            fill = QLinearGradient(fill_rect.left(), fill_rect.top(), fill_rect.right(), fill_rect.top())
            start = accent.lighter(110)
            end = QColor(accent)
            fill.setColorAt(0.0, start)
            fill.setColorAt(1.0, end)
            painter.setBrush(fill)
            painter.drawRoundedRect(fill_rect, groove_rect.height() / 2, groove_rect.height() / 2)

        handle_rect = QRectF(handle_x - handle_radius, handle_cy - handle_radius, handle_radius * 2, handle_radius * 2)
        painter.setBrush(handle_fill)
        painter.setPen(QPen(handle_border, 1.0))
        painter.drawEllipse(handle_rect)

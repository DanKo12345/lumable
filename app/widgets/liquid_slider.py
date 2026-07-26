from __future__ import annotations

import math

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSequentialAnimationGroup, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSlider

from app.motion_policy import motion_policy
from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import play_or_complete


class LiquidSlider(QSlider):
    def __init__(self, accent="neutral", parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._scale = 1.0
        self.setMinimumHeight(56)
        self.accent = accent
        self._track_gradient: list[tuple[float, QColor]] | None = None
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

        # Connect on the slider itself so Qt drops the signal when it's destroyed.
        motion_policy.changed.connect(self._on_motion_changed)
        if motion_policy.reduced:
            self._on_motion_changed(True)

    def _on_motion_changed(self, reduced: bool) -> None:
        if not reduced:
            return
        # Reduced motion: kill every decorative feedback and settle at neutral;
        # the numeric readout jumps straight to the real value.
        for anim in (
            self._hover_anim,
            self._press_anim,
            self._landing_group,
            self._wheel_group,
            self._impact_anim,
            self._display_anim,
        ):
            anim.stop()
        self._hover = 0.0
        self._press = 0.0
        self._impact = 0.0
        self._display_value = float(self.value())
        self.update()

    def set_accent_color(self, accent: str):
        self.accent = accent
        self.update()

    def set_track_gradient(self, stops: list[tuple[float, tuple[int, int, int]]] | None) -> None:
        """Paint the whole groove with a fixed colour gradient (e.g. warm→cool for
        a temperature slider) instead of the flat groove + accent fill."""
        if stops is None:
            self._track_gradient = None
        else:
            self._track_gradient = [(float(off), QColor(*rgb)) for off, rgb in stops]
        self.update()

    def set_render_scale(self, scale: float) -> None:
        """Scale the slider's height and internal geometry (handle, glow, groove)
        together so it stays proportional and the glow never clips when compact."""
        self._scale = max(0.6, min(1.6, float(scale)))
        self.setMinimumHeight(max(40, round(56 * self._scale)))
        self.update()

    def jump_to(self, value: int) -> None:
        """Set the value without animation/signals, keeping the handle in sync.

        Plain ``setValue`` under ``blockSignals`` leaves the painted handle at its
        old position (the handle follows ``_display_value``, updated via the
        valueChanged signal). Use this when syncing a slider from saved settings.
        """
        self.blockSignals(True)
        self.setValue(int(value))
        self.blockSignals(False)
        self._display_value = float(self.value())
        self.update()

    def _accent_color(self) -> QColor:
        palette = {
            "red": QColor("#ff7d86"),
            "green": QColor("#55d2a4"),
            "blue": QColor("#76a9ff"),
            "yellow": QColor("#e7c563"),
            "purple": QColor("#b58fff"),
            "white": QColor("#f4f7ff"),
            "neutral": QColor("#8fbfff"),
        }
        # A near-white accent (brightness) is invisible on the light groove, so
        # give it a soft cool tone in the light theme while keeping it white in
        # the dark theme.
        if self.accent == "white" and not theme_manager.is_dark:
            return QColor("#9fb6dd")
        return QColor(palette.get(self.accent, palette["neutral"]))

    def enterEvent(self, event):
        if not motion_policy.reduced:
            self._hover_anim.stop()
            self._hover_anim.setStartValue(self._hover)
            self._hover_anim.setEndValue(1.0)
            self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if motion_policy.reduced:
            self._hover = 0.0
            self.update()
        else:
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

        # The value change always applies; only the decorative wheel pulse is
        # gated by reduced motion.
        if not motion_policy.reduced:
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
        if motion_policy.reduced:
            return  # no press glow under reduced motion
        self._wheel_group.stop()
        self._landing_group.stop()
        self._impact_anim.stop()
        self._impact = 0.0
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(1.0)
        self._press_anim.start()

    def _press_out(self):
        if motion_policy.reduced:
            return  # no landing / impact feedback under reduced motion
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
        play_or_complete(self._display_anim)  # reduced motion snaps the readout

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
        if not theme_manager.is_dark:
            groove_color.setAlpha(72)
        handle_fill = QColor(255, 255, 255, 245)
        handle_border = QColor(255, 255, 255, 90) if theme_manager.is_dark else QColor(80, 130, 210, 90)

        s = self._scale
        left = 14.0 * s
        right = self.width() - 14.0 * s
        cy = self.height() / 2 + 3.0 * s
        groove_h = (7.2 + self._hover * 0.8 + self._press * 0.55) * s
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

        handle_radius = (9.3 + self._hover * 1.5 + self._press * 2.7 + self._impact * 0.45) * s
        handle_cy = cy - self._press * 1.6 * s + landing_drop + shake_y

        glow_radius = (18.0 + self._hover * 6.5 + self._press * 7.5 + self._impact * 3.2) * s
        glow = QRadialGradient(handle_x, handle_cy, glow_radius)
        glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 96 if theme_manager.is_dark else 64))
        glow.setColorAt(0.50, QColor(accent.red(), accent.green(), accent.blue(), 34 if theme_manager.is_dark else 22))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        glow_rect = QRectF(handle_x - glow_radius, handle_cy - glow_radius, glow_radius * 2, glow_radius * 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(glow_rect)

        painter.setPen(Qt.NoPen)
        if self._track_gradient is not None:
            # Fixed-colour track (e.g. warm→cool temperature): the whole groove is
            # the gradient and there's no accent fill — the handle shows position.
            track = QLinearGradient(groove_rect.left(), 0.0, groove_rect.right(), 0.0)
            for offset, color in self._track_gradient:
                track.setColorAt(offset, color)
            painter.setBrush(track)
            painter.drawRoundedRect(groove_rect, groove_rect.height() / 2, groove_rect.height() / 2)
        else:
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

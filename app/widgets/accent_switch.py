from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.accent_color import subdued_led_accent
from app.widgets.animation_helpers import play_or_complete


class AccentSwitch(QAbstractButton):
    """A real checkable switch whose active colour follows the strip accent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(54, 30)
        self._progress = 0.0
        self._show_focus_ring = False
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._set_progress)
        self.toggled.connect(self._animate_to_state)

    def _accent(self) -> QColor:
        return subdued_led_accent()

    def _animate_to_state(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        self._animation.stop()
        if not self.isVisible():
            self._progress = target
            self.update()
            return
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        play_or_complete(self._animation)

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    def showEvent(self, event) -> None:
        self._progress = 1.0 if self.isChecked() else 0.0
        super().showEvent(event)

    def focusInEvent(self, event) -> None:
        self._show_focus_ring = event.reason() != Qt.MouseFocusReason
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        self._show_focus_ring = False
        super().focusOutEvent(event)
        self.update()

    def hideEvent(self, event) -> None:
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = rect.height() / 2.0
        palette = theme_manager.palette

        field = qcolor_from_token(palette["field"])
        surface = qcolor_from_token(palette["surface"])
        field_mix = field.alphaF()
        off = QColor(
            round(surface.red() + (field.red() - surface.red()) * field_mix),
            round(surface.green() + (field.green() - surface.green()) * field_mix),
            round(surface.blue() + (field.blue() - surface.blue()) * field_mix),
        )
        on = self._accent()
        progress = self._progress
        track = QColor(
            round(off.red() + (on.red() - off.red()) * progress),
            round(off.green() + (on.green() - off.green()) * progress),
            round(off.blue() + (on.blue() - off.blue()) * progress),
            235 if self.isEnabled() else 105,
        )
        painter.setPen(QPen(qcolor_from_token(palette["field_border"]), 1.0))
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)

        knob_size = rect.height() - 6.0
        knob_x = rect.left() + 3.0 + (rect.width() - knob_size - 6.0) * progress
        knob = QColor(255, 255, 255, 245 if self.isEnabled() else 150)
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(knob_x, rect.top() + 3.0, knob_size, knob_size))

        if self._show_focus_ring and self.isEnabled():
            ring = self._accent()
            ring.setAlpha(220)
            painter.setPen(QPen(ring, 2.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
        painter.end()

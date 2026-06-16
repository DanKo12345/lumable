from __future__ import annotations

import re

from PySide6.QtCore import Property, QEasingCurve, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QLabel, QStyle, QStyleOption

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import make_property_animation, restart_animation


class ValueChip(QLabel):
    activated = Signal()

    def __init__(self, text: str, parent=None) -> None:
        super().__init__("", parent)
        self._current_text = str(text)
        self._next_text = str(text)
        self._roll = 1.0
        self._roll_direction = 1
        self._roll_anim = make_property_animation(self, b"rollValue", 140, QEasingCurve.OutCubic)
        super().setText(str(text))
        self.setObjectName("valueChip")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(68)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def get_roll_value(self) -> float:
        return self._roll

    def set_roll_value(self, value: float) -> None:
        self._roll = float(value)
        if self._roll >= 0.999:
            self._current_text = self._next_text
        self.update()

    rollValue = Property(float, get_roll_value, set_roll_value)

    def setText(self, text: str) -> None:
        text = str(text)
        if text == self._next_text:
            super().setText(text)
            return
        old_value = self._numeric_value(self._next_text)
        new_value = self._numeric_value(text)
        self._current_text = self._next_text
        self._next_text = text
        if old_value is not None and new_value is not None:
            self._roll_direction = 1 if new_value >= old_value else -1
        else:
            self._roll_direction = 1
        super().setText(text)
        restart_animation(self._roll_anim, 0.0, 1.0)

    @staticmethod
    def _numeric_value(text: str) -> int | None:
        match = re.search(r"-?\d+", text)
        return int(match.group(0)) if match else None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.rect())
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)

        rect = QRectF(self.rect())
        font = self.font()
        painter.setFont(font)
        base = qcolor_from_token(theme_manager.palette["text"])
        if not self.isEnabled():
            base.setAlpha(120)
        progress = max(0.0, min(1.0, self._roll))
        direction = float(self._roll_direction)
        height = rect.height()

        old_alpha = int(255 * max(0.0, 1.0 - progress * 1.45))
        if progress < 0.999 and self._current_text:
            old_color = QColor(base)
            old_color.setAlpha(old_alpha)
            painter.setPen(old_color)
            y = -direction * progress * height * 0.62
            painter.drawText(rect.translated(0.0, y), Qt.AlignCenter, self._current_text)

        new_color = QColor(base)
        new_color.setAlpha(int(255 * min(1.0, 0.35 + progress * 0.95)))
        painter.setPen(new_color)
        y = direction * (1.0 - progress) * height * 0.62
        painter.drawText(rect.translated(0.0, y), Qt.AlignCenter, self._next_text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space}:
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)

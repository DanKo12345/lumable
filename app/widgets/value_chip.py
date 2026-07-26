from __future__ import annotations

import re

from PySide6.QtCore import Property, QAbstractAnimation, QEasingCurve, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import QAbstractButton, QStyle, QStyleOption

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import make_property_animation, restart_animation


class ValueChip(QAbstractButton):
    """The numeric readout next to a slider; clicking it opens a value editor.

    A QAbstractButton rather than a styled QLabel: it behaves as a button, so it
    must report itself as one. As a QLabel it announced itself as static text,
    which tells a screen-reader user there is nothing to activate here.
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._current_text = str(text)
        self._next_text = str(text)
        self._purpose = ""
        self._roll = 1.0
        self._roll_direction = 1
        self._roll_anim = make_property_animation(self, b"rollValue", 170, QEasingCurve.OutQuint)
        super().setText(str(text))
        self.setObjectName("valueChip")
        self.setAttribute(Qt.WA_StyledBackground)
        # Fixed (not just minimum) width so the readout boxes line up in one
        # vertical column instead of jumping around with their content.
        self.setFixedWidth(74)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._refresh_accessible_name()

    def set_purpose(self, purpose: str) -> None:
        """Name what this readout controls, e.g. "Brightness".

        The value alone ("50%") is meaningless read out on its own — the label
        that gives it meaning lives in a separate widget at the other end of the
        row, which assistive tools have no reason to connect to this one.
        """
        self._purpose = str(purpose)
        self._refresh_accessible_name()

    def _refresh_accessible_name(self) -> None:
        value = self._next_text
        self.setAccessibleName(f"{self._purpose}: {value}" if self._purpose else value)

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
            self._refresh_accessible_name()
            return
        old_value = self._numeric_value(self._next_text)
        new_value = self._numeric_value(text)
        running = self._roll_anim.state() == QAbstractAnimation.Running
        # If a roll is still playing (fast slider drag), don't snap back to 0 —
        # that's what makes rapid changes look jerky. Instead just retarget the
        # incoming text and keep the same slide direction, so the readout glides
        # continuously toward the newest value in a single smooth motion.
        if not running:
            self._current_text = self._next_text
            if old_value is not None and new_value is not None:
                self._roll_direction = 1 if new_value >= old_value else -1
            else:
                self._roll_direction = 1
        self._next_text = text
        super().setText(text)
        self._refresh_accessible_name()
        if not running:
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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Space is QAbstractButton's own; Enter is added to match the buttons
        # around it. Auto-repeat is ignored so holding the key opens one editor
        # rather than firing on every repeat.
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and not event.isAutoRepeat():
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

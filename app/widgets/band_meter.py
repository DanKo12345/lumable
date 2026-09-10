"""A thin level line along the bottom of a band row in the music card.

It only draws. What it shows and how fast it moves is decided by the music
card's controller from the latest reading, once per interface tick.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from app.theme import theme_manager

# How the shown level chases the measured one. Up fast, so a hit is seen when it
# lands; down slowly, so one quiet block does not make the line flicker.
ATTACK_S = 0.03
RELEASE_S = 0.28
# How long the bass line stays brightened after a beat.
FLASH_S = 0.18
# A meter is a reading, not a control: at rest it is drawn quieter than the
# sliders around it, and only the moment a beat lands gets full strength.
RESTING_OPACITY = 0.68


def follow_level(shown: float, target: float, dt: float) -> float:
    """One step of the meter's ballistics over ``dt`` seconds."""
    if dt <= 0.0:
        return shown
    tau = ATTACK_S if target > shown else RELEASE_S
    return shown + (target - shown) * (1.0 - math.exp(-dt / tau))


class BandMeter(QWidget):
    """The line itself. Draws nothing while no sound is being listened to, so
    the card looks exactly as it did before the meters existed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor(88, 182, 255)
        self._live = False
        self._level = 0.0
        self._flash = 0.0
        self._painted: tuple | None = None

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def level(self) -> float:
        return self._level

    def flash(self) -> float:
        return self._flash

    def is_live(self) -> bool:
        return self._live

    def set_state(self, live: bool, level: float, flash: float = 0.0) -> None:
        self._live = bool(live)
        self._level = max(0.0, min(1.0, float(level)))
        self._flash = max(0.0, min(1.0, float(flash)))
        # Repainted only when the picture would change by a whole pixel, so a
        # level that moves in the fourth decimal costs nothing.
        painted = (self._live, round(self._level * self.width()), round(self._flash * 8))
        if painted != self._painted:
            self._painted = painted
            self.update()

    def paintEvent(self, event) -> None:
        if not self._live:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        rect = QRectF(self.rect())
        radius = rect.height() / 2.0
        track = QColor(255, 255, 255, 26) if theme_manager.is_dark else QColor(30, 40, 70, 26)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)
        width = rect.width() * self._level
        if width >= 0.5:
            fill = QColor(self._color)
            if self._flash > 0.0:
                fill = fill.lighter(100 + round(45 * self._flash))
            fill.setAlphaF(RESTING_OPACITY + (1.0 - RESTING_OPACITY) * self._flash)
            painter.setBrush(fill)
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top(), max(width, rect.height()), rect.height()), radius, radius
            )
        painter.end()

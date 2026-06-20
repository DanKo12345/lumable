from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.theme import qcolor_from_token, theme_manager


class AmbientPreview(QWidget):
    """A full-width bar that shows the colour currently sent to the strip.

    Styled to match the effect preview strip (rounded, glossy, themed border)
    so the ambient card fits the rest of the UI. Shows a neutral surface when
    idle and the live colour with a soft gloss when streaming.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._color: tuple[int, int, int] | None = None

    def set_color(self, red: int, green: int, blue: int) -> None:
        self._color = (int(red), int(green), int(blue))
        self.update()

    def clear(self) -> None:
        self._color = None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 5.0, -1.0, -5.0)
        radius = min(16.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        is_dark = theme_manager.is_dark
        palette = theme_manager.palette

        if self._color is None:
            # Idle: a soft accent-tinted sweep instead of a dead dark bar, hinting
            # that this strip will glow with the screen colour once enabled.
            accent = qcolor_from_token(palette["accent_start"])
            base = QLinearGradient(rect.left(), 0, rect.right(), 0)
            base.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 30 if is_dark else 40))
            base.setColorAt(0.5, QColor(accent.red(), accent.green(), accent.blue(), 14 if is_dark else 22))
            base.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 30 if is_dark else 40))
            surface = qcolor_from_token(palette["surface_strong" if is_dark else "surface_soft"])
            painter.fillPath(path, surface)
            painter.fillPath(path, base)
            hint = QLinearGradient(0, rect.top(), 0, rect.bottom())
            hint.setColorAt(0.0, QColor(255, 255, 255, 26 if is_dark else 50))
            hint.setColorAt(0.5, QColor(255, 255, 255, 0))
            painter.fillPath(path, hint)
        else:
            color = QColor(*self._color)
            fill = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
            fill.setColorAt(0.0, color.lighter(120))
            fill.setColorAt(0.5, color)
            fill.setColorAt(1.0, color.darker(122))
            painter.fillPath(path, fill)
            gloss = QLinearGradient(0, rect.top(), 0, rect.bottom())
            gloss.setColorAt(0.0, QColor(255, 255, 255, 70))
            gloss.setColorAt(0.4, QColor(255, 255, 255, 12))
            gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, gloss)

        border = qcolor_from_token(palette["surface_border"])
        border.setAlpha(90 if is_dark else 110)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

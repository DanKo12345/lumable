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
        self._raw: tuple[int, int, int] | None = None  # dual "source → result" mode
        # Which of the two shapes to draw. Kept apart from the colours because
        # the two halves now arrive separately, and "no result yet" must not be
        # mistaken for "this is the one-capsule kind".
        self._single = False

    def set_color(self, red: int, green: int, blue: int) -> None:
        self._color = (int(red), int(green), int(blue))
        self._raw = None
        self._single = True
        self.update()

    def set_colors(self, raw: tuple[int, int, int], final: tuple[int, int, int]) -> None:
        """Show the screen's raw colour on the left and what the strip gets on
        the right — the shaping and smoothing made visible."""
        self._raw = (int(raw[0]), int(raw[1]), int(raw[2]))
        self._color = (int(final[0]), int(final[1]), int(final[2]))
        self._single = False
        self.update()

    def set_source(self, rgb: tuple[int, int, int]) -> None:
        """Replace only the left-hand capsule: the screen as it was captured."""
        self._raw = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        self._single = False
        self.update()

    def set_final(self, rgb: tuple[int, int, int]) -> None:
        """Replace only the right-hand capsule, keeping the screen colour shown.

        The two halves arrive from different places and at different rates: the
        screen's own colour comes from the capture, the result from whatever
        delivery carried it — about three captures for every one of those. Taken
        together they would blink the left half in step with the right, which is
        a rate the capture never ran at.
        """
        self._color = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        self._single = False
        self.update()

    def clear_final(self) -> None:
        """Nothing is being shown any more, but the screen is still being read."""
        if self._color is None:
            return
        self._color = None
        self.update()

    def clear(self) -> None:
        self._color = None
        self._raw = None
        self._single = False
        self.update()

    def _fill_capsule(self, painter: QPainter, rect: QRectF, rgb: tuple[int, int, int]) -> None:
        radius = min(16.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        color = QColor(*rgb)
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
        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(90 if theme_manager.is_dark else 110)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

    @staticmethod
    def _dual_rects(rect: QRectF) -> tuple[QRectF, QRectF]:
        gap = 26.0  # room for the arrow between the two capsules
        half = max(8.0, (rect.width() - gap) / 2.0)
        left = QRectF(rect.left(), rect.top(), half, rect.height())
        right = QRectF(rect.right() - half, rect.top(), half, rect.height())
        return left, right

    @staticmethod
    def _draw_arrow(painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(qcolor_from_token(theme_manager.palette["text_soft"]), 2.0))
        cx = int(rect.center().x())
        cy = int(rect.center().y())
        painter.drawLine(cx - 5, cy, cx + 4, cy)
        painter.drawLine(cx, cy - 4, cx + 4, cy)
        painter.drawLine(cx, cy + 4, cx + 4, cy)

    def _fill_placeholder(self, painter: QPainter, rect: QRectF) -> None:
        # A calm accent-tinted capsule for the off state, so "Screen → Strip"
        # reads before the sync starts and the layout doesn't jump on start.
        is_dark = theme_manager.is_dark
        palette = theme_manager.palette
        radius = min(16.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, qcolor_from_token(palette["surface_strong" if is_dark else "surface_soft"]))
        accent = qcolor_from_token(palette["accent_start"])
        tint = QLinearGradient(rect.left(), 0, rect.right(), 0)
        tint.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 26 if is_dark else 34))
        tint.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 12 if is_dark else 18))
        painter.fillPath(path, tint)
        border = qcolor_from_token(palette["surface_border"])
        border.setAlpha(80 if is_dark else 100)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 5.0, -1.0, -5.0)

        # Legacy single colour (set_color) — full-width capsule.
        if self._single and self._color is not None:
            self._fill_capsule(painter, rect, self._color)
            return

        # Always two capsules with an arrow — running shows raw → final, idle
        # shows two calm placeholders, so the shape is identical either way.
        # Each half stands or falls on its own: the screen can be read while
        # nothing is going out, and a result can arrive before the first capture
        # has been drawn.
        left, right = self._dual_rects(rect)
        for half, colour in ((left, self._raw), (right, self._color)):
            if colour is None:
                self._fill_placeholder(painter, half)
            else:
                self._fill_capsule(painter, half, colour)
        self._draw_arrow(painter, rect)

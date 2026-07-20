from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from app.theme import theme_manager
from app.widgets.section_icon import LUCIDE_ICON_DIR


class IconTile(QWidget):
    """A rounded, colour-tinted tile with a Lucide glyph inside.

    This is the leading element of a list row (the sleep moon, the sunrise sun):
    the tint carries the meaning at a glance, so the row reads before the text
    does. The tile keeps its own colour instead of following the theme accent —
    a moon that turns amber when the strip is amber would be noise, not signal.
    """

    TILE = 34
    RADIUS = 10.0
    GLYPH = 19

    def __init__(self, kind: str, tint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._tint = QColor(tint)
        self._renderer = QSvgRenderer(str(LUCIDE_ICON_DIR / f"{kind}.svg"), self)
        self.setFixedSize(self.TILE, self.TILE)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def sizeHint(self) -> QSize:
        return QSize(self.TILE, self.TILE)

    def set_tint(self, tint: str) -> None:
        self._tint = QColor(tint)
        self.update()

    def _glyph_color(self) -> QColor:
        color = QColor(self._tint)
        if not theme_manager.is_dark:
            # The same hue would wash out on a light surface; deepen it instead
            # of picking a second palette to keep in sync.
            color = color.darker(178)
        return color

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
        fill = QColor(self._tint)
        # The light theme needs a denser wash: the same alpha that reads as a
        # tinted tile on charcoal disappears into white.
        fill.setAlpha(46 if theme_manager.is_dark else 68)
        painter.fillPath(path, fill)

        if not self._renderer.isValid():
            return
        # Render the glyph at native pixel density: thin Lucide strokes look
        # stepped if drawn small and scaled up afterwards.
        pixel_ratio = self.devicePixelRatioF()
        offset = (self.TILE - self.GLYPH) / 2
        glyph_rect = QRectF(offset, offset, self.GLYPH, self.GLYPH)

        image = QImage(
            round(self.width() * pixel_ratio),
            round(self.height() * pixel_ratio),
            QImage.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(pixel_ratio)
        image.fill(Qt.transparent)
        svg_painter = QPainter(image)
        svg_painter.setRenderHint(QPainter.Antialiasing)
        self._renderer.render(svg_painter, glyph_rect)
        svg_painter.end()

        tinted = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
        tinted.setDevicePixelRatio(pixel_ratio)
        tinted.fill(Qt.transparent)
        tint_painter = QPainter(tinted)
        tint_painter.fillRect(tinted.rect(), self._glyph_color())
        tint_painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        tint_painter.drawImage(0, 0, image)
        tint_painter.end()

        painter.drawImage(0, 0, tinted)

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from app.theme import qcolor_from_token, theme_manager

LUCIDE_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons" / "lucide"


class SectionIcon(QWidget):
    ICON_BOX = 26
    GLYPH_SIZE = 21

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._renderer = QSvgRenderer(str(LUCIDE_ICON_DIR / f"{kind}.svg"), self)
        self.setFixedSize(self.ICON_BOX, self.ICON_BOX)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def sizeHint(self) -> QSize:
        return QSize(self.ICON_BOX, self.ICON_BOX)

    def paintEvent(self, event) -> None:
        if not self._renderer.isValid():
            return
        icon_size = self.GLYPH_SIZE
        icon_rect = QRectF(
            (self.width() - icon_size) / 2,
            (self.height() - icon_size) / 2,
            icon_size,
            icon_size,
        )
        image = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)

        svg_painter = QPainter(image)
        svg_painter.setRenderHint(QPainter.Antialiasing)
        self._renderer.render(svg_painter, icon_rect)
        svg_painter.end()

        tint = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
        tint.fill(Qt.transparent)
        tint_painter = QPainter(tint)
        icon_color = qcolor_from_token(theme_manager.palette["text"])
        icon_color.setAlpha(230 if theme_manager.is_dark else 238)
        tint_painter.fillRect(tint.rect(), icon_color)
        tint_painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        tint_painter.drawImage(0, 0, image)
        tint_painter.end()

        target_painter = QPainter(self)
        target_painter.setRenderHint(QPainter.Antialiasing)
        target_painter.drawImage(0, 0, tint)
        target_painter.end()

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget


class DiyPreviewStrip(QWidget):
    """A rounded strip that previews a DIY effect's colour sequence as a looping
    gradient (smooth) or hard colour bands (cut)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors: list[tuple[int, int, int]] = [(40, 40, 44)]
        self._smooth = True
        self.setMinimumHeight(26)

    def set_colors(self, colors: list[tuple[int, int, int]]) -> None:
        self._colors = [tuple(c) for c in colors] or [(40, 40, 44)]
        self.update()

    def set_smooth(self, smooth: bool) -> None:
        self._smooth = bool(smooth)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        grad = QLinearGradient(rect.left(), 0.0, rect.right(), 0.0)
        colors = self._colors
        if len(colors) == 1:
            grad.setColorAt(0.0, QColor(*colors[0]))
            grad.setColorAt(1.0, QColor(*colors[0]))
        else:
            seq = [*colors, colors[0]]  # loop back so it reads as a cycle
            span = len(seq) - 1
            for index, color in enumerate(seq):
                qc = QColor(*color)
                if self._smooth:
                    grad.setColorAt(index / span, qc)
                else:
                    grad.setColorAt(min(1.0, index / span), qc)
                    if index < span:
                        grad.setColorAt(min(1.0, (index + 1) / span - 1e-4), qc)
        painter.fillPath(path, grad)

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.theme import qcolor_from_token, theme_manager


def paint_color_tile(
    painter: QPainter,
    rect: QRectF,
    color: QColor,
    *,
    border_color: QColor,
    selected: bool = False,
    radius_ratio: float = 0.28,
) -> None:
    radius = min(rect.width(), rect.height()) * radius_ratio
    shell = QPainterPath()
    shell.addRoundedRect(rect, radius, radius)

    base = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    base.setColorAt(0.0, QColor(255, 255, 255, 34))
    base.setColorAt(0.45, QColor(255, 255, 255, 14))
    base.setColorAt(1.0, QColor(255, 255, 255, 5))
    painter.fillPath(shell, base)

    edge = QColor(border_color)
    edge.setAlpha(min(160, edge.alpha() + (34 if selected else 0)))
    painter.setPen(QPen(edge, 1.1))
    painter.drawPath(shell)

    inset = rect.adjusted(5.0, 5.0, -5.0, -5.0)
    inner_radius = min(inset.width(), inset.height()) * radius_ratio
    inner = QPainterPath()
    inner.addRoundedRect(inset, inner_radius, inner_radius)

    fill = QLinearGradient(inset.left(), inset.top(), inset.left(), inset.bottom())
    fill.setColorAt(0.0, color.lighter(132))
    fill.setColorAt(0.38, color.lighter(112))
    fill.setColorAt(1.0, color.darker(115))
    painter.fillPath(inner, fill)

    color_edge = QColor(color)
    color_edge.setAlpha(94 if selected else 70)
    painter.setPen(QPen(color_edge, 1.0))
    painter.drawPath(inner)

    shine_rect = QRectF(inset.left() + 4.5, inset.top() + 3.5, inset.width() * 0.42, inset.height() * 0.26)
    shine = QPainterPath()
    shine.addRoundedRect(shine_rect, shine_rect.height() / 2.0, shine_rect.height() / 2.0)
    painter.setPen(Qt.NoPen)
    painter.fillPath(shine, QColor(255, 255, 255, 58))


class ColorSwatch(QWidget):
    clicked = Signal()
    rightClicked = Signal()

    def __init__(
        self,
        theme_provider: Callable[[], dict[str, str]],
        parent: QWidget | None = None,
        *,
        radius_ratio: float = 0.5,
    ) -> None:
        super().__init__(parent)
        self._theme_provider = theme_provider
        self._color = QColor(88, 182, 255)
        # 0.5 = circle (square widget); lower values give a rounded rectangle.
        self._radius_ratio = radius_ratio
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("")

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.setToolTip(f"RGB {color.red()}, {color.green()}, {color.blue()}")
        self.update()

    def color(self) -> QColor:
        return QColor(self._color)

    def mouseReleaseEvent(self, event) -> None:
        if self.rect().contains(event.position().toPoint()):
            if event.button() == Qt.LeftButton:
                self.clicked.emit()
            elif event.button() == Qt.RightButton:
                self.rightClicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        tokens = self._theme_provider()
        border_color = qcolor_from_token(tokens.get("surface_border", "rgba(255,255,255,0.18)"))
        if theme_manager.is_dark and self._color.lightness() < 40:
            border_color.setAlpha(min(255, border_color.alpha() + 80))
        if not theme_manager.is_dark and self._color.lightness() < 60:
            border_color = QColor(60, 80, 140, 120)
        paint_color_tile(
            painter,
            rect,
            self._color,
            border_color=border_color,
            radius_ratio=self._radius_ratio,
        )

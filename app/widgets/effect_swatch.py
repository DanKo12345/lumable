from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from app.widgets.effect_preview_strip import effect_semantic_key

_SINGLE = {
    "red": QColor(255, 92, 112),
    "green": QColor(94, 226, 178),
    "blue": QColor(118, 174, 255),
    "yellow": QColor(255, 216, 100),
    "cyan": QColor(88, 226, 232),
    "magenta": QColor(197, 118, 255),
    "white": QColor(245, 248, 255),
}
_PALETTE = [
    QColor(255, 92, 112),
    QColor(94, 226, 178),
    QColor(118, 174, 255),
    QColor(88, 226, 232),
    QColor(197, 118, 255),
    QColor(255, 216, 100),
    QColor(245, 248, 255),
]


def _single_color(semantic_key: str) -> QColor:
    for token, color in _SINGLE.items():
        if token in semantic_key:
            return QColor(color)
    return QColor(118, 174, 255)


def _fill_swatch(painter: QPainter, path: QPainterPath, rect: QRectF, semantic_key: str) -> None:
    if "rainbow" in semantic_key or ("spectrum" in semantic_key and not semantic_key.startswith("flash")):
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        stops = 12
        for index in range(stops + 1):
            pos = index / stops
            grad.setColorAt(pos, QColor.fromHsvF(pos, 0.62, 1.0))
        painter.fillPath(path, grad)
    elif semantic_key.startswith("jump"):
        palette = (
            [QColor(255, 92, 112), QColor(94, 226, 178), QColor(118, 174, 255)]
            if semantic_key == "jump_rgb"
            else _PALETTE
        )
        seg = rect.width() / len(palette)
        for index, color in enumerate(palette):
            painter.fillRect(QRectF(rect.left() + index * seg, rect.top(), seg + 1.0, rect.height()), color)
    elif semantic_key.startswith("flash"):
        if "spectrum" in semantic_key:
            grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
            for index, color in enumerate(_PALETTE):
                grad.setColorAt(index / (len(_PALETTE) - 1), color)
            painter.fillPath(path, grad)
        else:
            color = _single_color(semantic_key)
            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            grad.setColorAt(0.0, color.lighter(150))
            grad.setColorAt(0.5, color)
            grad.setColorAt(1.0, color.darker(125))
            painter.fillPath(path, grad)
    elif semantic_key.startswith("fade"):
        if semantic_key == "fade_red_green":
            colors = [QColor(255, 92, 112), QColor(94, 226, 178)]
        elif semantic_key == "fade_red_blue":
            colors = [QColor(255, 92, 112), QColor(118, 174, 255)]
        elif semantic_key == "fade_green_blue":
            colors = [QColor(94, 226, 178), QColor(118, 174, 255)]
        else:
            colors = [_single_color(semantic_key)]
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        if len(colors) == 1:
            color = colors[0]
            grad.setColorAt(0.0, color.darker(140))
            grad.setColorAt(0.5, color.lighter(125))
            grad.setColorAt(1.0, color.darker(140))
        else:
            for index, color in enumerate(colors):
                grad.setColorAt(index / (len(colors) - 1), color)
        painter.fillPath(path, grad)
    else:
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        grad.setColorAt(0.0, QColor(96, 180, 255))
        grad.setColorAt(0.5, QColor(158, 132, 255))
        grad.setColorAt(1.0, QColor(96, 180, 255))
        painter.fillPath(path, grad)


def _draw_lock(painter: QPainter, cx: float, cy: float, size: float) -> None:
    painter.save()
    white = QColor(255, 255, 255, 238)
    painter.setPen(Qt.NoPen)
    painter.setBrush(white)
    body = QRectF(cx - size * 0.42, cy - size * 0.02, size * 0.84, size * 0.6)
    painter.drawRoundedRect(body, size * 0.14, size * 0.14)
    pen = QPen(white, max(1.0, size * 0.16))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    shackle = QRectF(cx - size * 0.28, cy - size * 0.52, size * 0.56, size * 0.64)
    painter.drawArc(shackle, 0, 180 * 16)
    painter.restore()


def effect_swatch_icon(
    effect_key: str,
    effect_code: int,
    *,
    is_dark: bool,
    locked: bool = False,
    width: int = 32,
    height: int = 18,
) -> QIcon:
    """A tiny gradient chip that previews how an effect looks, for combo rows."""
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(0.5, 0.5, width - 1.0, height - 1.0)
    radius = 5.0
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path)

    semantic_key = effect_semantic_key(effect_key, effect_code)
    _fill_swatch(painter, path, rect, semantic_key)

    top_light = QLinearGradient(0, rect.top(), 0, rect.bottom())
    top_light.setColorAt(0.0, QColor(255, 255, 255, 72))
    top_light.setColorAt(0.5, QColor(255, 255, 255, 0))
    painter.fillPath(path, top_light)

    if locked:
        painter.fillPath(path, QColor(8, 12, 24, 152))
        _draw_lock(painter, rect.center().x(), rect.center().y(), height * 0.52)

    painter.setClipping(False)
    edge = QColor(255, 255, 255, 40 if is_dark else 72)
    painter.setPen(QPen(edge, 1.0))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.end()
    return QIcon(pixmap)

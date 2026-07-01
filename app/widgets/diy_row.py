from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.theme import qcolor_from_token, theme_manager

_DRAG_SCALE = 1.04


class DiyRow(QWidget):
    """A colour-step row that paints its own rounded background, lightens on hover
    (like the Configs rows), and can be dragged to reorder. The drag ghost is a
    clean snapshot of the row itself, kept right under the cursor."""

    def __init__(self, drag_key: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.drag_key = str(drag_key)
        self._hover = False
        self._press_pos: QPoint | None = None

    # ── hover ─────────────────────────────────────────────────────────
    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    # ── drag ──────────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < 12:
            super().mouseMoveEvent(event)
            return
        grab_pos = self._press_pos
        self._press_pos = None

        pixmap = self.grab()
        scaled = pixmap.scaled(
            round(pixmap.width() * _DRAG_SCALE),
            round(pixmap.height() * _DRAG_SCALE),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        mime = QMimeData()
        mime.setText(self.drag_key)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(scaled)
        drag.setHotSpot(QPoint(round(grab_pos.x() * _DRAG_SCALE), round(grab_pos.y() * _DRAG_SCALE)))
        drag.exec(Qt.MoveAction)

    # ── paint ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 12.0, 12.0)

        is_dark = theme_manager.is_dark
        if self._hover:
            bg = qcolor_from_token(theme_manager.palette["list_hover"])
        else:
            bg = QColor(255, 255, 255, 18) if is_dark else QColor(100, 130, 210, 18)
        border = QColor(255, 255, 255, 26) if is_dark else QColor(100, 130, 210, 48)

        painter.fillPath(path, bg)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)

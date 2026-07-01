from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDrag, QPixmap, QRegion
from PySide6.QtWidgets import QListWidget


class DiyList(QListWidget):
    """A list whose drag ghost is slightly enlarged — a small 'lift' when you grab
    a colour step to reorder it. The reorder itself is the standard InternalMove
    (the drop is still handled by the base class, so rowsMoved fires as usual)."""

    DRAG_SCALE = 1.05

    def startDrag(self, supportedActions) -> None:
        item = self.currentItem()
        indexes = self.selectedIndexes()
        if item is None or not indexes:
            super().startDrag(supportedActions)
            return
        rect = self.visualItemRect(item)
        if rect.isEmpty():
            super().startDrag(supportedActions)
            return
        pixmap = QPixmap(rect.size())
        pixmap.fill(Qt.transparent)
        self.viewport().render(pixmap, QPoint(0, 0), QRegion(rect))
        scaled = pixmap.scaled(
            round(rect.width() * self.DRAG_SCALE),
            round(rect.height() * self.DRAG_SCALE),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData(indexes))
        drag.setPixmap(scaled)
        drag.setHotSpot(QPoint(scaled.width() // 2, scaled.height() // 2))
        drag.exec(supportedActions, Qt.MoveAction)

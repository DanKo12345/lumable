from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget


class DragReorderList(QWidget):
    """A vertical stack of draggable rows with smooth, clean reordering.

    Each row widget carries a ``drag_key`` attribute; dragging one and dropping
    it moves it in the stack. The drag ghost is the row's own snapshot (set by the
    row's ``mouseMoveEvent``), so there's no washed-out duplicate — unlike a
    QListWidget item-widget drag. Emits ``reordered`` with the new key order.
    """

    reordered = Signal(list)

    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(spacing)

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def add_row(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def _widgets(self) -> list[QWidget]:
        out = []
        for index in range(self._layout.count()):
            widget = self._layout.itemAt(index).widget()
            if widget is not None:
                out.append(widget)
        return out

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        key = event.mimeData().text()
        widgets = self._widgets()
        dragged = next((w for w in widgets if getattr(w, "drag_key", None) == key), None)
        if dragged is None:
            return
        drop_y = event.position().toPoint().y()
        others = [w for w in widgets if w is not dragged]
        target = len(others)
        for index, widget in enumerate(others):
            if drop_y < widget.y() + widget.height() / 2:
                target = index
                break
        others.insert(target, dragged)
        for widget in widgets:
            self._layout.removeWidget(widget)
        for widget in others:
            self._layout.addWidget(widget)
        event.acceptProposedAction()
        self.reordered.emit([getattr(w, "drag_key", "") for w in others])

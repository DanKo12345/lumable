from PySide6.QtCore import Property, QPoint, QPointF, Qt
from PySide6.QtGui import QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QSizePolicy, QWidget


class CollapsingRow(QWidget):
    """Reserve space before revealing content; fade before releasing space."""

    _HEIGHT_PHASE = 0.65

    @staticmethod
    def _ease(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def __init__(self, content: QWidget, gap: int) -> None:
        super().__init__()
        self.content = content
        content.setParent(self)
        self._gap = gap
        self._content_height = max(1, content.sizeHint().height())
        self._progress = 0.0
        self._snapshot = None
        self._capturing = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(0)
        content.hide()

    def set_content_height(self, height: int) -> None:
        self._content_height = height
        self._place_content()
        self.set_progress(self._progress)

    def _place_content(self) -> None:
        self.content.setGeometry(0, 0, self.width(), self._content_height)

    def prepare_transition(self) -> None:
        # Reuse the same pixels when reversing halfway through a transition.
        if self._snapshot is None:
            self._place_content()
            self._capture()
        self.content.hide()

    def _capture(self) -> None:
        ratio = self.devicePixelRatioF()
        self._snapshot = QPixmap(round(self.width() * ratio), round(self._content_height * ratio))
        self._snapshot.setDevicePixelRatio(ratio)
        self._snapshot.fill(Qt.transparent)
        # render() delivers pending resize events on hidden panels as well.
        self._capturing = True
        try:
            self.content.render(self._snapshot, QPoint(), QRegion(), QWidget.DrawChildren)
        finally:
            self._capturing = False

    def get_progress(self) -> float:
        return self._progress

    def finish_transition(self) -> None:
        self.content.setVisible(self._progress == 1.0)
        self._snapshot = None
        self.update()

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        height_progress = self._ease(self._progress / self._HEIGHT_PHASE)
        self.setFixedHeight(round((self._content_height + self._gap) * height_progress))
        if self._snapshot is None:
            self.content.setVisible(self._progress == 1.0)
        self.update()

    progress = Property(float, get_progress, set_progress)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_content()
        if (self._snapshot is not None and not self._capturing
                and event.oldSize().width() != event.size().width()):
            self._capture()

    def paintEvent(self, event) -> None:
        if self._snapshot is None:
            return
        painter = QPainter(self)
        opacity = self._ease((self._progress - self._HEIGHT_PHASE) / (1.0 - self._HEIGHT_PHASE))
        painter.setOpacity(opacity)
        painter.drawPixmap(QPointF(0, 0), self._snapshot)
        painter.end()

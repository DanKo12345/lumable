import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from app.widgets.collapsing_row import CollapsingRow


class MarkedRow(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(10, 2, 20, 8, Qt.white)
        painter.end()


def render(slot):
    image = QImage(slot.width(), max(1, slot.height()), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    slot.render(image, QPoint(), QRegion(), QWidget.DrawChildren)
    return image


@pytest.mark.parametrize("opening", [True, False])
def test_row_fades_without_relayout_or_opaque_background(opening):
    app = QApplication.instance() or QApplication([])
    row = MarkedRow()
    slot = CollapsingRow(row, 5)
    slot.resize(200, 0)
    slot.set_content_height(48)
    slot.set_progress(0.0 if opening else 1.0)
    slot.show()
    app.processEvents()
    slot.prepare_transition()
    geometry = row.geometry()
    levels = []
    try:
        for progress in ((0.25, 0.5, 0.75) if opening else (0.75, 0.5, 0.25)):
            slot.set_progress(progress)
            app.processEvents()
            frame = render(slot)
            assert row.geometry() == geometry
            assert frame.pixelColor(100, 2).alpha() == 0
            levels.append(frame.pixelColor(15, 5).alpha())
        assert levels == sorted(levels, reverse=not opening)
        assert max(levels) - min(levels) > 100
        slot.set_progress(1.0 if opening else 0.0)
        height = slot.height()
        slot.finish_transition()
        app.processEvents()
        assert slot.height() == height
        assert row.isHidden() is not opening
    finally:
        slot.close()
        slot.deleteLater()
        app.processEvents()


def test_reversing_reuses_snapshot_and_finishes_with_live_content():
    app = QApplication.instance() or QApplication([])
    row = MarkedRow()
    slot = CollapsingRow(row, 5)
    slot.resize(200, 0)
    slot.set_content_height(48)
    slot.set_progress(1.0)
    slot.show()
    app.processEvents()
    try:
        slot.prepare_transition()
        slot.set_progress(0.45)
        before = render(slot)
        key = slot._snapshot.cacheKey()
        slot.prepare_transition()
        assert slot._snapshot.cacheKey() == key
        assert render(slot) == before
        slot.set_progress(1.0)
        before = render(slot)
        slot.finish_transition()
        assert render(slot) == before
        assert not row.isHidden()
        assert slot._snapshot is None
    finally:
        slot.close()
        slot.deleteLater()
        app.processEvents()

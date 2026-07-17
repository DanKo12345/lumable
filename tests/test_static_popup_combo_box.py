from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

from app.widgets.static_popup_combo_box import StaticPopupComboBox


def test_closed_combo_wheel_scrolls_page_without_changing_selection():
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    canvas = QWidget()
    layout = QVBoxLayout(canvas)
    combo = StaticPopupComboBox(lambda: {}, lambda: True, canvas)
    combo.addItem("Russian", "ru")
    combo.addItem("English", "en")
    layout.addWidget(combo)
    spacer = QWidget(canvas)
    spacer.setFixedHeight(900)
    layout.addWidget(spacer)
    scroll.setWidget(canvas)
    scroll.resize(320, 160)
    scroll.show()
    app.processEvents()

    event = QWheelEvent(
        QPointF(12, 12),
        QPointF(12, 12),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    combo.wheelEvent(event)

    assert combo.currentData() == "ru"
    assert scroll.verticalScrollBar().value() > 0

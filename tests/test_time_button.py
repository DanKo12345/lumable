from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.widgets.time_button import TimeButton


def test_time_picker_opens_rolls_and_accepts_without_nested_event_loop() -> None:
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    layout = QVBoxLayout(window)
    button = TimeButton("19:30")
    button.set_picker_title("Time")
    button.set_picker_labels(hours="Hours", minutes="Min", ok="OK")
    layout.addWidget(button)
    window.resize(500, 400)
    window.show()
    try:
        button._open_picker()
        app.processEvents()

        assert button._picker is not None
        button._picker.hour_column.step(1)
        button._picker.accept()
        app.processEvents()

        assert button.time() == QTime(20, 30)
        assert button._picker is None
    finally:
        if button._picker is not None:
            button._picker.reject()
        window.close()
        app.processEvents()

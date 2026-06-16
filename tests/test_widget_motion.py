from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.widgets.liquid_button import LiquidButton
from app.widgets.value_chip import ValueChip


def test_value_chip_rolls_between_numeric_values() -> None:
    app = QApplication.instance() or QApplication([])
    chip = ValueChip("10")
    try:
        chip.setText("25%")
        app.processEvents()

        assert chip.text() == "25%"
        assert chip._current_text == "10"
        assert chip._next_text == "25%"
        assert chip._roll_direction == 1
    finally:
        chip.deleteLater()
        app.processEvents()


def test_liquid_button_exposes_impact_animation_value() -> None:
    app = QApplication.instance() or QApplication([])
    button = LiquidButton("OK")
    try:
        button.set_impact(1.0)
        app.processEvents()

        assert button.get_impact() == 1.0
    finally:
        button.deleteLater()
        app.processEvents()

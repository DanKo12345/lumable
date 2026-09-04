from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
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


def test_navigation_hover_grows_the_material_without_dragging_its_content() -> None:
    app = QApplication.instance() or QApplication([])
    button = LiquidButton("Settings", "nav")
    button.resize(204, 44)
    try:
        button.set_scale(1.0)
        resting_material = button._animated_rect()
        resting_content = button._nav_content_rect()
        button.set_scale(1.04)
        hovered_material = button._animated_rect()
        hovered_content = button._nav_content_rect()

        assert hovered_material.width() > resting_material.width(), "hover stopped the spring"
        assert hovered_content == resting_content, "hover dragged the icon and label sideways"
    finally:
        button.deleteLater()
        app.processEvents()


def test_navigation_press_springs_the_icon_and_label_too() -> None:
    app = QApplication.instance() or QApplication([])
    button = LiquidButton("Settings", "nav")
    button.resize(204, 44)
    try:
        button.set_nav_content_scale(0.98)
        pressed = button._nav_content_rect()
        button.set_nav_content_scale(1.04)
        released_overshoot = button._nav_content_rect()
        button.set_nav_content_scale(1.0)
        settled = button._nav_content_rect()

        assert pressed.width() < settled.width() < released_overshoot.width()
    finally:
        button.deleteLater()
        app.processEvents()


def test_navigation_mouse_events_drive_the_content_spring() -> None:
    app = QApplication.instance() or QApplication([])
    button = LiquidButton("Settings", "nav")
    button.resize(204, 44)
    button.show()
    try:
        QTest.mousePress(button, Qt.LeftButton)
        assert button._nav_content_anim.keyValueAt(1.0) == 0.98

        QTest.mouseRelease(button, Qt.LeftButton)
        assert button._nav_content_anim.keyValueAt(0.58) == 1.04
        assert button._nav_content_anim.keyValueAt(1.0) == 1.0
    finally:
        button.deleteLater()
        app.processEvents()


def test_navigation_text_stays_vertically_centered_while_the_button_springs() -> None:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QFontMetricsF

    metrics = QFontMetricsF(QApplication.font())
    pressed = QRectF(20.0, 4.0, 100.0, 36.0)
    released_overshoot = QRectF(17.0, 1.0, 106.0, 42.0)

    pressed_origin = LiquidButton._centered_text_origin(pressed, metrics, "Settings")
    released_origin = LiquidButton._centered_text_origin(released_overshoot, metrics, "Settings")
    glyphs = metrics.tightBoundingRect("Settings")

    assert pressed_origin.x() != released_origin.x(), "text stopped following the click spring"
    assert pressed_origin.y() == released_origin.y(), "click changed the text baseline"
    assert pressed_origin.y() + glyphs.center().y() == pressed.center().y()

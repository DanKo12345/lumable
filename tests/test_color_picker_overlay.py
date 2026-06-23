from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from app.localization import localization_manager
from app.theme import theme_manager
from app.widgets.color_picker_overlay import (
    COLOR_PLANE_WIDTH,
    LABEL_WIDTH,
    PANEL_HEIGHT_COMPACT,
    PANEL_HEIGHT_WITH_HISTORY,
    PICKER_WIDTH,
    ROW_SIDE_MARGIN,
    VALUE_WIDTH,
    ColorPickerOverlay,
)
from app.widgets.liquid_slider import LiquidSlider


def _labels() -> dict[str, str]:
    return {
        "red": localization_manager.t("slider.red"),
        "green": localization_manager.t("slider.green"),
        "blue": localization_manager.t("slider.blue"),
        "hex": localization_manager.t("color.hex"),
        "recent": localization_manager.t("color.recent"),
        "cancel": localization_manager.t("dialog.cancel"),
        "ok": localization_manager.t("dialog.ok"),
    }


def test_color_picker_uses_consistent_grid_with_history() -> None:
    app = QApplication.instance() or QApplication([])
    picker = ColorPickerOverlay(
        localization_manager.t("dialog.pick_color"),
        QColor(10, 20, 30),
        _labels(),
        [{"r": 10, "g": 20, "b": 30}],
    )
    try:
        assert picker.findChild(QLineEdit, "colorPickerHexInput") is not None
        assert picker.color_plane.width() == COLOR_PLANE_WIDTH
        assert picker.color_plane.width() + picker.hue_bar.width() + 12 == PICKER_WIDTH

        labels = picker.findChildren(QLabel, "colorPickerLabel")
        values = picker.findChildren(QLabel, "colorPickerValue")
        sliders = picker.findChildren(LiquidSlider)

        assert {label.width() for label in labels} == {LABEL_WIDTH}
        assert {value.width() for value in values} == {VALUE_WIDTH}
        assert len(sliders) == 3
        assert picker.layout().itemAt(1).widget().height() == PANEL_HEIGHT_WITH_HISTORY
        assert ROW_SIDE_MARGIN == 14
    finally:
        picker.deleteLater()
        app.processEvents()


def test_color_picker_compact_height_without_history() -> None:
    app = QApplication.instance() or QApplication([])
    picker = ColorPickerOverlay(localization_manager.t("dialog.pick_color"), QColor(10, 20, 30), _labels(), [])
    try:
        assert picker.layout().itemAt(1).widget().height() == PANEL_HEIGHT_COMPACT
    finally:
        picker.deleteLater()
        app.processEvents()


def test_color_picker_accepts_pasted_hex_with_hash() -> None:
    app = QApplication.instance() or QApplication([])
    picker = ColorPickerOverlay(localization_manager.t("dialog.pick_color"), QColor(10, 20, 30), _labels(), [])
    try:
        picker.hex_input.setText("#FF5500")

        picker._apply_hex_input()

        selected = picker.selected_color()
        assert (selected.red(), selected.green(), selected.blue()) == (255, 85, 0)
        assert picker.hex_input.text() == "#ff5500"
    finally:
        picker.deleteLater()
        app.processEvents()


def test_color_picker_accepts_pasted_hex_without_hash() -> None:
    app = QApplication.instance() or QApplication([])
    picker = ColorPickerOverlay(localization_manager.t("dialog.pick_color"), QColor(10, 20, 30), _labels(), [])
    try:
        picker.hex_input.setText("3366cc")

        picker._apply_hex_input()

        selected = picker.selected_color()
        assert (selected.red(), selected.green(), selected.blue()) == (51, 102, 204)
        assert picker.hex_input.text() == "#3366cc"
    finally:
        picker.deleteLater()
        app.processEvents()


def test_color_picker_builds_for_all_languages_and_themes() -> None:
    app = QApplication.instance() or QApplication([])
    original_language = localization_manager.language
    original_theme = theme_manager.is_dark
    try:
        for language in ("ru", "en", "es", "zh"):
            localization_manager.set_language(language)
            for is_dark in (True, False):
                theme_manager.set_dark(is_dark)
                picker = ColorPickerOverlay(
                    localization_manager.t("dialog.pick_color"),
                    QColor(28, 79, 130),
                    _labels(),
                    [{"r": 28, "g": 79, "b": 130}],
                )
                try:
                    assert picker.findChild(QLineEdit, "colorPickerHexInput").text() == "#1c4f82"
                    label_texts = {label.text() for label in picker.findChildren(QLabel, "colorPickerLabel")}
                    assert localization_manager.t("slider.red") in label_texts
                    assert localization_manager.t("slider.green") in label_texts
                    assert localization_manager.t("slider.blue") in label_texts
                    assert localization_manager.t("color.hex") in label_texts
                finally:
                    picker.deleteLater()
                    app.processEvents()
    finally:
        localization_manager.set_language(original_language)
        theme_manager.set_dark(original_theme)

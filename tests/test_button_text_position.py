import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.theme import theme_manager
from app.widgets.liquid_button import LiquidButton


def render_nav(button, scale, dpr):
    button.set_nav_content_scale(scale)
    image = QImage(round(button.width() * dpr), round(button.height() * dpr),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        button._paint_nav(painter, button._animated_rect(), button._nav_content_rect())
    finally:
        painter.end()
    return image


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_nav_spring_has_no_raster_jump_at_unit_scale(dpr):
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    button = LiquidButton("Settings", "nav_active")
    button.resize(204, 44)
    button.setFont(QFont("Segoe UI", 10))
    button.set_icon_kind("settings")
    try:
        assert QFontMetrics(button.font()).inFont("S")
        resting = render_nav(button, 1.0, dpr)
        for scale in (0.99999, 1.00001):
            frame = render_nav(button, scale, dpr)
            # Check the icon and letters separately so a blank background
            # cannot dilute the discontinuity at the end of the spring.
            for left, right in ((20, 36), (46, 110)):
                deltas = [abs(frame.pixelColor(x, y).alpha() - resting.pixelColor(x, y).alpha())
                          for y in range(round(12*dpr), round(32*dpr))
                          for x in range(round(left*dpr), round(right*dpr))]
                assert sum(deltas) / len(deltas) < 1.0
        original = button._nav_text_cache[1].cacheKey()
        for scale in (0.98, 1.008, 1.0305, 1.0327, 1.0206, 1.0061, 1.0008, 1.0):
            render_nav(button, scale, dpr)
            assert button._nav_text_cache[1].cacheKey() == original
        button.setText("Changed")
        assert render_nav(button, 1.0, dpr) != resting
        assert button._nav_text_cache[1].cacheKey() != original
    finally:
        button.deleteLater()
        app.processEvents()
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


def render_content(button, scale, dpr):
    button.set_scale(scale)
    image = QImage(round(button.width() * dpr), round(button.height() * dpr),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        painter.setFont(button.font())
        painter.setPen(QColor("white"))
        button._draw_content(painter, button._animated_rect(), QColor("white"))
    finally:
        painter.end()
    return image


@pytest.mark.parametrize("icon", ["", "settings"])
@pytest.mark.parametrize("height,dpr", [(32, 1.0), (33, 1.25), (42, 1.5), (43, 2.0)])
def test_hover_keeps_the_rendered_label_in_place(icon, height, dpr):
    app = QApplication.instance() or QApplication([])
    font = QFont("Segoe UI", 10)
    font_id = -1
    if not QFontMetrics(font).inFont("S"):
        font_path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font_path))
    assert QFontMetrics(font).inFont("S"), "The render must contain letters, not missing-glyph boxes"
    button = LiquidButton("Settings")
    button.setMinimumHeight(0)
    button.resize(201, height)
    button.setFont(font)
    button.set_icon_kind(icon)
    try:
        resting = render_content(button, 1.0, dpr)
        resting_rect = button._animated_rect()
        for scale in (1.003, 1.012, 1.023, 1.034, 1.04):
            assert render_content(button, scale, dpr) == resting, f"text moved at {scale}"
        assert button._animated_rect().width() > resting_rect.width()
    finally:
        button.deleteLater()
        app.processEvents()
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_navigation_click_scales_letters_without_sliding_the_label(dpr):
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    previous_dark = theme_manager.is_dark
    theme_manager.set_dark(True)
    button = LiquidButton("Settings", "nav_active")
    button.setFont(QFont("Segoe UI", 10))
    button.set_icon_kind("settings")
    button.resize(204, 44)
    bounds = []
    try:
        assert QFontMetrics(button.font()).inFont("S")
        for scale in (1.0, 0.98, 1.04, 1.0):
            button.set_nav_content_scale(scale)
            image = QImage(round(204 * dpr), round(44 * dpr), QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            try:
                button._paint_nav(painter, button._animated_rect(), button._nav_content_rect())
            finally:
                painter.end()
            pixels = [(x, y) for y in range(image.height()) for x in range(round(45*dpr), image.width())
                      if (c := image.pixelColor(x, y)).alpha() > 200
                      and min(c.red(), c.green(), c.blue()) > 240]
            assert pixels, "The frame must contain visible letters"
            bounds.append((min(x for x, y in pixels), max(x for x, y in pixels)))
        assert max(left for left, right in bounds) - min(left for left, right in bounds) <= dpr
        assert bounds[2][1] > bounds[1][1], "the letters must still spring"
        assert bounds[0] == bounds[-1], "release must return to the original position"
    finally:
        button.deleteLater()
        app.processEvents()
        theme_manager.set_dark(previous_dark)
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)

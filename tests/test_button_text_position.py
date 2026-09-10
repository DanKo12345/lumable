import os
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QFont, QFontDatabase, QFontMetrics, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.theme import theme_manager
from app.widgets.liquid_button import NAV_HOVER_SCALE, LiquidButton


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


def channel_drift(left, right):
    """Largest single-channel difference between two renders of the same label."""
    worst = 0
    for y in range(left.height()):
        for x in range(left.width()):
            a, b = left.pixelColor(x, y), right.pixelColor(x, y)
            worst = max(worst, abs(a.red() - b.red()), abs(a.green() - b.green()),
                        abs(a.blue() - b.blue()), abs(a.alpha() - b.alpha()))
    return worst


def draw_nav_text_directly(self, painter, content, font, color):
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(self._centered_text_origin(content, QFontMetricsF(font), self.text()), self.text())


@pytest.mark.parametrize("role", ["nav", "nav_active"])
@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_resting_navigation_text_is_as_sharp_as_plain_text(monkeypatch, role, dpr):
    # The spring rasterizes the label so letters cannot re-hint mid-animation.
    # At rest that layer must land on the device grid untouched: supersampling
    # it and scaling back down costs ~18% of the edge contrast at DPR 1.0.
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    button = LiquidButton("Settings", role)
    button.resize(204, 44)
    button.setFont(QFont("Segoe UI", 10))
    button.set_icon_kind("settings")
    try:
        assert QFontMetrics(button.font()).inFont("S"), "The render must contain letters, not boxes"
        cached = render_nav(button, 1.0, dpr)
        button._nav_text_cache = None
        monkeypatch.setattr(LiquidButton, "_draw_nav_text", draw_nav_text_directly)
        plain = render_nav(button, 1.0, dpr)
        # Compositing the layer over the active background rounds one channel
        # of one pixel; resampling a supersampled layer moves whole stems by up
        # to 184 of 255, so a one-step tolerance still fails on the regression.
        assert channel_drift(cached, plain) <= 1, "the resting label is resampled, not drawn on the grid"
    finally:
        button.deleteLater()
        app.processEvents()
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


def settle_hover(button, entering):
    """Point at the item (or away) and let the growth animation land."""
    if entering:
        spot = QPointF(100, 22)
        button.enterEvent(QEnterEvent(spot, spot, spot))
    else:
        button.leaveEvent(QEvent(QEvent.Leave))
    button._nav_hover_anim.setCurrentTime(button._nav_hover_anim.duration())


def label_bounds(image, dpr):
    """Bounding box of the label, in device pixels, ignoring the icon column."""
    left, top, right, bottom = round(44 * dpr), round(8 * dpr), round(150 * dpr), round(36 * dpr)
    marks = [(x, y) for y in range(top, bottom) for x in range(left, right)
             if image.pixelColor(x, y).alpha() > 60]
    assert marks, "no label was rendered"
    return (min(x for x, _ in marks), min(y for _, y in marks),
            max(x for x, _ in marks), max(y for _, y in marks))


def nav_button(text="Settings", role="nav_active"):
    button = LiquidButton(text, role)
    button.resize(204, 44)
    button.setFont(QFont("Segoe UI", 10))
    button.set_icon_kind("settings")
    return button


@pytest.mark.parametrize("dpr", [1.0, 1.5])
def test_pointing_at_a_navigation_item_grows_its_label_from_a_fixed_left_edge(dpr):
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    button = nav_button()
    try:
        assert QFontMetrics(button.font()).inFont("S"), "The render must contain letters, not boxes"
        resting = label_bounds(render_nav(button, 1.0, dpr), dpr)
        settle_hover(button, True)
        hovered = label_bounds(render_nav(button, 1.0, dpr), dpr)
        # 6% of a short label is only a couple of pixels, so measure the widened
        # run rather than expecting a dramatic jump.
        assert hovered[2] - resting[2] >= 1, "the label did not grow under the pointer"
        assert button._nav_hover_scale == pytest.approx(NAV_HOVER_SCALE)
        # Scaling nudges the faintest edge column by up to one pixel; a label that
        # slid would move its whole run, not its fringe.
        assert abs(hovered[0] - resting[0]) <= 1, "the label slid instead of growing from its left edge"
        settle_hover(button, False)
        assert label_bounds(render_nav(button, 1.0, dpr), dpr) == resting
    finally:
        button.deleteLater()
        app.processEvents()
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


def test_releasing_a_click_over_a_hovered_item_stays_under_a_tenth(monkeypatch):
    # The click spring and the pointer growth multiply. A release over a hovered
    # item peaks at the product, and past ~1.09 the label starts crowding its
    # neighbours, so the spring's overshoot is deliberately smaller here.
    app = QApplication.instance() or QApplication([])
    button = nav_button()
    try:
        settle_hover(button, True)
        button._handle_button_press(50, 22)
        spring = button._nav_content_anim
        spring.setCurrentTime(spring.duration())
        button._handle_button_release()
        peak = 0.0
        for step in range(spring.duration() + 1):
            spring.setCurrentTime(step)
            peak = max(peak, button._nav_content_scale * button._nav_hover_scale)
        assert peak > NAV_HOVER_SCALE, "the release lost its overshoot"
        assert peak <= 1.09, f"the combined overshoot reached {peak:.4f}"
    finally:
        button.deleteLater()
        app.processEvents()


def test_a_hovered_label_is_only_scaled_never_redrawn():
    # Redrawing the label at the grown size re-fits its glyphs to another pixel
    # grid, so the word crept sideways after it had stopped growing and crept
    # back when the pointer left. One raster, only scaled, from rest to rest.
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    button = nav_button()
    try:
        assert QFontMetrics(button.font()).inFont("S"), "The render must contain letters, not boxes"
        resting = render_nav(button, 1.0, 1.0)
        raster = button._nav_text_cache[1].cacheKey()
        settle_hover(button, True)
        render_nav(button, 1.0, 1.0)
        assert button._nav_text_cache[1].cacheKey() == raster, "the hovered label was redrawn"
        settle_hover(button, False)
        assert render_nav(button, 1.0, 1.0) == resting
        assert button._nav_text_cache[1].cacheKey() == raster
    finally:
        button.deleteLater()
        app.processEvents()
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


def accent_columns(image):
    """Leftmost and rightmost columns of the saturated accent bar."""
    columns = [x for x in range(image.width()) for y in range(image.height())
               if max(image.pixelColor(x, y).getRgb()[:3]) - min(image.pixelColor(x, y).getRgb()[:3]) > 60]
    assert columns, "no accent bar was drawn"
    return min(columns), max(columns)


@pytest.mark.parametrize("scale", [1.04, 1.0439])  # the hover spring and its overshoot
def test_the_current_sections_accent_bar_does_not_ride_the_hover_spring(scale):
    # The highlight may grow under the pointer, but the bar marks the current
    # section: drawn from the growing highlight it walked three pixels left.
    app = QApplication.instance() or QApplication([])
    button = LiquidButton("Settings", "nav_active")
    button.resize(204, 44)
    try:
        resting = accent_columns(render_nav(button, 1.0, 1.0))
        button.set_scale(scale)
        assert accent_columns(render_nav(button, 1.0, 1.0)) == resting, f"the bar moved at {scale}"
    finally:
        button.deleteLater()
        app.processEvents()


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

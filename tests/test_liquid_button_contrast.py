"""Regression guard: filled button labels must keep WCAG-readable contrast.

The filled roles (accent / danger) paint their own label colour instead of a
stylesheet one, and quick-mode accents can dye the fill with light pastels.
This pins the model-level contrast ratio — label colour against the composited
gradient midpoint — at or above 4.5:1 for every stock combination, so a future
palette tweak cannot silently produce an unreadable primary button.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.quick_modes import QUICK_MODES
from app.theme import theme_manager
from app.widgets.liquid_button import LiquidButton

MINIMUM_CONTRAST = 4.5

_MODE_ACCENTS = {
    mode.key: mode.accent for mode in QUICK_MODES if getattr(mode, "accent", None)
}


@pytest.fixture(autouse=True)
def _restore_theme_state():
    previous_dark = theme_manager.is_dark
    previous_override = theme_manager._accent_override
    yield
    theme_manager.set_dark(previous_dark)
    theme_manager.set_accent_override(previous_override)


def _label_contrast(role: str) -> float:
    app = QApplication.instance() or QApplication([])
    button = LiquidButton("x", role)
    try:
        lc = button._light_palette()
        text = button._fill_label_color(lc)
        top, bottom = button._role_base_colors(lc)
        fill_lum = button._composite_fill_luminance(top, bottom)
        text_lum = button._relative_luminance(text)
        lighter = max(fill_lum, text_lum)
        darker = min(fill_lum, text_lum)
        return (lighter + 0.05) / (darker + 0.05)
    finally:
        button.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("is_dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("role", ["accent", "danger"])
def test_default_accent_label_contrast(is_dark: bool, role: str) -> None:
    theme_manager.set_dark(is_dark)
    theme_manager.set_accent_override(None)
    assert _label_contrast(role) >= MINIMUM_CONTRAST


@pytest.mark.parametrize("is_dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("mode_key", sorted(_MODE_ACCENTS))
def test_quick_mode_accent_label_contrast(is_dark: bool, mode_key: str) -> None:
    theme_manager.set_dark(is_dark)
    theme_manager.set_accent_override(_MODE_ACCENTS[mode_key])
    assert _label_contrast("accent") >= MINIMUM_CONTRAST

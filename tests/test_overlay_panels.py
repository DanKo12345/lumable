"""Every floating panel must take its fill from one place.

The same blue-grey gradient used to be copy-pasted into ten overlays, so the
dialogs drifted blue while the app's cards were graphite — and each fix only
corrected the one window someone happened to be looking at.
"""

from __future__ import annotations

import re
from pathlib import Path

WIDGETS = Path(__file__).resolve().parent.parent / "app" / "widgets"

# Panels that paint a full-surface gradient behind their content.
PANEL_FILES = [
    "about_overlay.py",
    "api_connect_overlay.py",
    "color_picker_overlay.py",
    "lan_access_overlay.py",
    "license_overlay.py",
    "logs_overlay.py",
    "pair_phone_overlay.py",
    "profile_action_overlay.py",
    "time_button.py",
    "update_overlay.py",
]

_LITERAL_FILL = re.compile(r"fill\.setColorAt\(\s*[\d.]+\s*,\s*QColor\(\s*\d+")


def test_every_overlay_panel_uses_the_shared_colours() -> None:
    for name in PANEL_FILES:
        source = (WIDGETS / name).read_text(encoding="utf-8")
        assert "overlay_panel_colors()" in source, f"{name} does not use the shared panel colours"
        assert not _LITERAL_FILL.search(source), f"{name} hardcodes a panel gradient stop"


def test_dark_panel_is_graphite_not_blue() -> None:
    from app.theme import overlay_panel_colors, theme_manager

    was_dark = theme_manager.is_dark
    try:
        theme_manager.set_dark(True)
        for color in overlay_panel_colors():
            spread = max(color.red(), color.green(), color.blue()) - min(
                color.red(), color.green(), color.blue()
            )
            # A neutral graphite has near-equal channels; the old values were
            # ~16 apart, which is what read as "blue windows".
            assert spread <= 5, f"dark panel stop {color.name()} is tinted, not graphite"
    finally:
        theme_manager.set_dark(was_dark)

from __future__ import annotations

from PySide6.QtGui import QColor

from app.theme import qcolor_from_token, theme_manager


def led_accent_color() -> QColor:
    """Return the live strip colour, with the theme accent as a safe fallback."""
    glow = getattr(theme_manager, "led_glow", None)
    if glow is not None and QColor(glow).isValid():
        return QColor(glow)
    return qcolor_from_token(theme_manager.palette["accent_end"])


def subdued_led_accent() -> QColor:
    """Composite the live colour like the translucent ``led`` button fill.

    Painting the raw colour opaquely makes saturated blues shout and turns a
    white strip into a white slab. The primary button already avoids that with
    transparency; custom controls need the equivalent solid paint colour.
    """
    accent = led_accent_color()
    surface = qcolor_from_token(theme_manager.palette["surface"])
    strength = 0.48 if theme_manager.is_dark else 0.64
    return QColor(
        round(surface.red() + (accent.red() - surface.red()) * strength),
        round(surface.green() + (accent.green() - surface.green()) * strength),
        round(surface.blue() + (accent.blue() - surface.blue()) * strength),
    )

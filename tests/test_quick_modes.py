from __future__ import annotations

from app.quick_modes import QUICK_MODE_MAP


def test_rainbow_quick_mode_uses_flowing_spectrum_effect() -> None:
    rainbow = QUICK_MODE_MAP["rainbow"]

    assert rainbow.effect_code == 0x8A
    assert rainbow.speed == 35

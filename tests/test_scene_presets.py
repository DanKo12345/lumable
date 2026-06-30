from __future__ import annotations

from app.scene_presets import SCENE_PRESETS, get_scene_preset


def test_presets_have_unique_keys() -> None:
    keys = [preset.key for preset in SCENE_PRESETS]
    assert len(keys) == len(set(keys))
    assert len(keys) >= 4


def test_presets_are_valid_colours_and_brightness() -> None:
    for preset in SCENE_PRESETS:
        assert len(preset.rgb) == 3
        assert all(0 <= channel <= 255 for channel in preset.rgb)
        assert 0 <= preset.brightness <= 100


def test_get_scene_preset_lookup() -> None:
    first = SCENE_PRESETS[0]
    assert get_scene_preset(first.key) is first
    assert get_scene_preset("does-not-exist") is None

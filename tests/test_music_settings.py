from __future__ import annotations

from app.storage import DEFAULT_SETTINGS, validate_music


def test_defaults_when_empty() -> None:
    result = validate_music({})
    assert result == DEFAULT_SETTINGS["music"]


def test_non_dict_falls_back_to_defaults() -> None:
    assert validate_music("nonsense") == DEFAULT_SETTINGS["music"]
    assert validate_music(None) == DEFAULT_SETTINGS["music"]


def test_sliders_are_clamped_0_100() -> None:
    result = validate_music({"saturation": 999, "smoothing": -5, "speed": 250})
    assert result["saturation"] == 100
    assert result["smoothing"] == 0
    assert result["speed"] == 100


def test_speed_present_with_default() -> None:
    # A config saved before the speed slider existed still gets a valid speed.
    legacy = {"saturation": 70, "smoothing": 40}
    assert validate_music(legacy)["speed"] == DEFAULT_SETTINGS["music"]["speed"]


def test_band_colors_coerced_and_clamped() -> None:
    result = validate_music(
        {
            "colors": {
                "bass": {"r": 300, "g": -10, "b": 128},
                "mid": "garbage",
                "treble": {"r": 10, "g": 20, "b": 30},
            }
        }
    )
    assert result["colors"]["bass"] == {"r": 255, "g": 0, "b": 128}
    # Bad band -> falls back to that band's default.
    assert result["colors"]["mid"] == DEFAULT_SETTINGS["music"]["colors"]["mid"]
    assert result["colors"]["treble"] == {"r": 10, "g": 20, "b": 30}


def test_unknown_keys_dropped() -> None:
    result = validate_music({"saturation": 50, "bogus": 1})
    assert set(result.keys()) == {"saturation", "smoothing", "speed", "beat", "gate", "source", "device", "mic_device", "colors"}

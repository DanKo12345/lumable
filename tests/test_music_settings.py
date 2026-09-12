from __future__ import annotations

import pytest

from app.storage import DEFAULT_SETTINGS, validate_music


def test_defaults_when_empty() -> None:
    result = validate_music({})
    assert result == DEFAULT_SETTINGS["music"]


def test_non_dict_falls_back_to_defaults() -> None:
    assert validate_music("nonsense") == DEFAULT_SETTINGS["music"]
    assert validate_music(None) == DEFAULT_SETTINGS["music"]


def test_sliders_are_clamped_0_100() -> None:
    result = validate_music(
        {"saturation": 999, "smoothing": -5, "speed": 250, "sensitivity": -20}
    )
    assert result["saturation"] == 100
    assert result["smoothing"] == 0
    assert result["speed"] == 100
    assert result["sensitivity"] == 0


def test_speed_present_with_default() -> None:
    # A config saved before the speed slider existed still gets a valid speed.
    legacy = {"saturation": 70, "smoothing": 40}
    assert validate_music(legacy)["speed"] == DEFAULT_SETTINGS["music"]["speed"]


def test_legacy_settings_get_default_bass_sensitivity() -> None:
    legacy = {"saturation": 70, "smoothing": 40, "beat": 60}
    assert (
        validate_music(legacy)["sensitivity"]
        == DEFAULT_SETTINGS["music"]["sensitivity"]
    )


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
    assert set(result.keys()) == {
        "saturation",
        "smoothing",
        "speed",
        "beat",
        "sensitivity",
        "gate_db",
        "source",
        "device",
        "mic_device",
        "colors",
    }


def test_an_old_gate_percent_is_stored_as_the_same_threshold_in_decibels() -> None:
    from app.music_gate import LEGACY_RMS_PER_PERCENT, rms_for_db

    migrated = validate_music({"gate": 16})
    assert "gate" not in migrated, "the old percent was kept beside its replacement"
    assert rms_for_db(migrated["gate_db"]) == pytest.approx(16 * LEGACY_RMS_PER_PERCENT, rel=1e-3)


def test_a_saved_decibel_gate_is_kept_and_clamped() -> None:
    assert validate_music({"gate": 16, "gate_db": -45.0})["gate_db"] == -45.0
    assert validate_music({"gate_db": -200})["gate_db"] == -70.0


def test_an_old_settings_file_is_rewritten_with_the_decibel_gate() -> None:
    import json

    from app import storage
    from app.music_gate import LEGACY_RMS_PER_PERCENT, rms_for_db

    # What an older build left on disk: a linear 16 % on the microphone.
    storage.SETTINGS_PATH.write_text(json.dumps({"music": {"gate": 16, "source": "mic"}}), encoding="utf-8")
    loaded = storage.load_settings()
    assert rms_for_db(loaded["music"]["gate_db"]) == pytest.approx(16 * LEGACY_RMS_PER_PERCENT, rel=1e-3)
    on_disk = json.loads(storage.SETTINGS_PATH.read_text(encoding="utf-8"))["music"]
    assert on_disk["gate_db"] == loaded["music"]["gate_db"], "the migrated value was not written back"
    assert "gate" not in on_disk, "the old percent stayed in the file"

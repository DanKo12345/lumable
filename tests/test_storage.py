from __future__ import annotations

import json

from app import storage


def test_validate_profile_clamps_values_and_fills_defaults() -> None:
    profile = storage.validate_profile(
        {
            "name": "Custom",
            "power": "off",
            "brightness": "999",
            "speed": "-5",
            "effect_code": "300",
            "color": {"r": "-1", "g": "bad", "b": "999"},
        }
    )

    assert profile is not None
    assert profile["power"] is False
    assert profile["brightness"] == 100
    assert profile["speed"] == 0
    assert profile["effect_code"] == 255
    assert profile["color"] == {"r": 0, "g": 182, "b": 255}
    assert "schedule" not in profile


def test_validate_profile_keeps_scene_schedule_when_present() -> None:
    profile = storage.validate_profile(
        {
            "name": "Evening scene",
            "schedule": {
                "enabled": "yes",
                "on_time": "21:5",
                "off_time": "25:00",
                "startup_enabled": "yes",
            },
        }
    )

    assert profile is not None
    assert profile["schedule"] == {
        "enabled": True,
        "on_time": "21:05",
        "off_time": "23:00",
        "startup_enabled": True,
        "days": [0, 1, 2, 3, 4, 5, 6],
    }


def test_validate_profile_rejects_empty_profile() -> None:
    assert storage.validate_profile({}) is None
    assert storage.validate_profile("broken") is None


def test_validate_settings_normalizes_broken_payload() -> None:
    settings = storage.validate_settings(
        {
            "theme_mode": "unknown",
            "theme": "broken",
            "language": None,
            "last_device_address": " AA:BB ",
            "last_device_name": " Desk strip ",
            "color_history": [
                {"r": 1, "g": 2, "b": 3},
                {"r": 1, "g": 2, "b": 3},
                {"r": "999", "g": "-1", "b": "bad"},
                "broken",
            ],
            "schedule": {
                "enabled": "yes",
                "on_time": "7:5",
                "off_time": "99:00",
                "startup_enabled": "yes",
            },
            "window_width": "wide",
            "window_height": 10,
            "last_state": {
                "power": "no",
                "brightness": "150",
                "speed": "-20",
                "effect_code": "bad",
                "color": {"r": 500, "g": -3, "b": "bad"},
            },
        }
    )

    assert settings["theme_mode"] == "auto"
    assert settings["theme"] == "light"
    assert settings["capture_compatibility"] is True
    assert settings["language"] == "ru"
    assert settings["updates_last_auto_check_at"] == 0
    assert settings["last_device_address"] == "AA:BB"
    assert settings["last_device_name"] == "Desk strip"
    assert settings["license"] == {
        "activated": False,
        "edition": "free",
        "kind": "",
        "provider": "",
        "license_key": "",
        "license_id": "",
        "instance_id": "",
        "checked_at": "",
        "grace_days": 7,
    }
    assert settings["color_history"] == [
        {"r": 1, "g": 2, "b": 3},
        {"r": 255, "g": 0, "b": 0},
    ]
    assert settings["schedule"] == {
        "enabled": True,
        "on_time": "07:05",
        "off_time": "23:00",
        "startup_enabled": True,
        "days": [0, 1, 2, 3, 4, 5, 6],
    }
    assert settings["window_width"] == 1320
    assert settings["window_height"] == 600
    assert settings["last_state"]["power"] is False
    assert settings["last_state"]["brightness"] == 100
    assert settings["last_state"]["speed"] == 0
    assert settings["last_state"]["effect_code"] == 0
    assert settings["last_state"]["color"] == {"r": 255, "g": 0, "b": 255}


def test_validate_settings_migrates_legacy_dark_start_color() -> None:
    settings = storage.validate_settings(
        {
            "last_state": {
                "brightness": 40,
                "color": {"r": 10, "g": 20, "b": 30},
            }
        }
    )

    assert settings["last_state"]["brightness"] == 100


def test_validate_settings_keeps_custom_quick_modes_as_scene_payloads() -> None:
    settings = storage.validate_settings(
        {
            "custom_quick_modes": [
                {
                    "key": "custom_1",
                    "name": "Desk",
                    "power": True,
                    "brightness": 80,
                    "speed": 30,
                    "effect_code": 0,
                    "color": {"r": 10, "g": 20, "b": 30},
                    "accent": "3366cc",
                    "schedule": {"enabled": True, "on_time": "20:00", "off_time": "23:00"},
                },
                "broken",
            ],
        }
    )

    assert settings["custom_quick_modes"] == [
        {
            "key": "custom_1",
            "preset_key": "",
            "name": "Desk",
            "power": True,
            "brightness": 80,
            "speed": 30,
            "effect_code": 0,
            "color": {"r": 10, "g": 20, "b": 30},
            "schedule": {
                "enabled": True,
                "on_time": "20:00",
                "off_time": "23:00",
                "startup_enabled": False,
                "days": [0, 1, 2, 3, 4, 5, 6],
            },
            "accent": "#3366cc",
        }
    ]
    assert settings["last_state"]["color"] == storage.DEFAULT_START_COLOR


def test_validate_settings_keeps_user_selected_dark_color() -> None:
    settings = storage.validate_settings(
        {
            "last_state": {
                "brightness": 70,
                "color": {"r": 10, "g": 20, "b": 30},
            }
        }
    )

    assert settings["last_state"]["brightness"] == 70
    assert settings["last_state"]["color"] == {"r": 10, "g": 20, "b": 30}


def test_load_profiles_skips_broken_entries_and_saves_cleaned_payload(tmp_path, monkeypatch) -> None:
    profiles_path = tmp_path / "profiles.json"
    settings_path = tmp_path / "settings.json"
    profiles_path.write_text(
        json.dumps(
            [
                {"name": "Valid", "brightness": 70, "color": {"r": 1, "g": 2, "b": 3}},
                {"brightness": 50},
                "broken",
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "PROFILES_PATH", profiles_path)
    monkeypatch.setattr(storage, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(storage, "_legacy_migration_pairs", lambda: [])
    monkeypatch.setattr(storage, "_migration_done", False)

    profiles = storage.load_profiles()

    assert any(profile["name"] == "Valid" for profile in profiles)
    assert all(isinstance(profile, dict) for profile in profiles)
    saved = json.loads(profiles_path.read_text(encoding="utf-8"))
    assert all(isinstance(profile, dict) for profile in saved)
    assert not any(profile.get("brightness") == 50 and not profile.get("name") for profile in saved)


def test_load_settings_saves_normalized_payload(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    profiles_path = tmp_path / "profiles.json"
    settings_path.write_text('{"window_width": "wide", "last_state": "broken"}', encoding="utf-8")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "PROFILES_PATH", profiles_path)
    monkeypatch.setattr(storage, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(storage, "_legacy_migration_pairs", lambda: [])
    monkeypatch.setattr(storage, "_migration_done", False)

    settings = storage.load_settings()

    assert settings["window_width"] == 1320
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved == settings


def test_ensure_data_dir_migrates_old_author_data_dir(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "new"
    old_author_dir = tmp_path / "dollza" / "LumaBLE"
    old_author_dir.mkdir(parents=True)
    old_profile = [{"name": "Old", "color": {"r": 1, "g": 2, "b": 3}}]
    old_settings = {"language": "en"}
    (old_author_dir / "profiles.json").write_text(json.dumps(old_profile), encoding="utf-8")
    (old_author_dir / "settings.json").write_text(json.dumps(old_settings), encoding="utf-8")

    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "PROFILES_PATH", data_dir / "profiles.json")
    monkeypatch.setattr(storage, "SETTINGS_PATH", data_dir / "settings.json")
    monkeypatch.setattr(storage, "_legacy_migration_pairs", lambda: [
        (old_author_dir / "profiles.json", data_dir / "profiles.json"),
        (old_author_dir / "settings.json", data_dir / "settings.json"),
    ])
    monkeypatch.setattr(storage, "_migration_done", False)

    storage._ensure_data_dir()

    assert json.loads((data_dir / "profiles.json").read_text(encoding="utf-8")) == old_profile
    assert json.loads((data_dir / "settings.json").read_text(encoding="utf-8")) == old_settings

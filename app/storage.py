from __future__ import annotations

import json
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
PROFILES_PATH = DATA_DIR / "profiles.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULT_PROFILES: list[dict[str, Any]] = [
    {
        "preset_key": "azure_drift",
        "name": "Лазурный дрейф",
        "power": True,
        "brightness": 92,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 72, "g": 163, "b": 255},
    },
    {
        "preset_key": "neon_sunset",
        "name": "Неоновый закат",
        "power": True,
        "brightness": 88,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 255, "g": 106, "b": 56},
    },
    {
        "preset_key": "polar_mint",
        "name": "Полярная мята",
        "power": True,
        "brightness": 84,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 112, "g": 255, "b": 214},
    },
    {
        "preset_key": "violet_pulse",
        "name": "Фиолетовый импульс",
        "power": True,
        "brightness": 86,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 170, "g": 96, "b": 255},
    },
    {
        "preset_key": "arctic_gold",
        "name": "Арктическое золото",
        "power": True,
        "brightness": 90,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 255, "g": 196, "b": 92},
    },
    {
        "preset_key": "pink_neon",
        "name": "Розовый неон",
        "power": True,
        "brightness": 87,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 255, "g": 92, "b": 168},
    },
    {
        "preset_key": "northern_sky",
        "name": "Северное небо",
        "power": True,
        "brightness": 91,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 96, "g": 138, "b": 255},
    },
    {
        "preset_key": "moon_lavender",
        "name": "Лунная лаванда",
        "power": True,
        "brightness": 85,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 198, "g": 166, "b": 255},
    },
    {
        "preset_key": "emerald_breeze",
        "name": "Изумрудный бриз",
        "power": True,
        "brightness": 89,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 76, "g": 232, "b": 180},
    },
    {
        "preset_key": "amber_dawn",
        "name": "Янтарный рассвет",
        "power": True,
        "brightness": 88,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 255, "g": 148, "b": 66},
    },
]

DEFAULT_PROFILE_NAME_TO_KEY = {
    "лазурный дрейф": "azure_drift",
    "azure drift": "azure_drift",
    "неоновый закат": "neon_sunset",
    "neon sunset": "neon_sunset",
    "полярная мята": "polar_mint",
    "polar mint": "polar_mint",
    "фиолетовый импульс": "violet_pulse",
    "violet pulse": "violet_pulse",
    "арктическое золото": "arctic_gold",
    "arctic gold": "arctic_gold",
    "розовый неон": "pink_neon",
    "pink neon": "pink_neon",
    "северное небо": "northern_sky",
    "northern sky": "northern_sky",
    "лунная лаванда": "moon_lavender",
    "moon lavender": "moon_lavender",
    "изумрудный бриз": "emerald_breeze",
    "emerald breeze": "emerald_breeze",
    "янтарный рассвет": "amber_dawn",
    "amber dawn": "amber_dawn",
}


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    _ensure_data_dir()
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_profiles() -> list[dict[str, Any]]:
    return json.loads(json.dumps(DEFAULT_PROFILES))


def _merge_missing_defaults(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_keys = {
        str(profile.get("preset_key", "")).strip().lower()
        for profile in profiles
        if str(profile.get("preset_key", "")).strip()
    }
    existing_names = {str(profile.get("name", "")).strip().lower() for profile in profiles}
    merged = list(profiles)
    for profile in default_profiles():
        preset_key = str(profile.get("preset_key", "")).strip().lower()
        name = str(profile.get("name", "")).strip().lower()
        if (preset_key and preset_key in existing_keys) or (name and name in existing_names):
            continue
        if preset_key or name:
            merged.append(profile)
    return merged


def _attach_missing_preset_keys(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    changed = False
    for profile in profiles:
        copy = dict(profile)
        if not str(copy.get("preset_key", "")).strip():
            name = str(copy.get("name", "")).strip().lower()
            preset_key = DEFAULT_PROFILE_NAME_TO_KEY.get(name)
            if preset_key:
                copy["preset_key"] = preset_key
                changed = True
        updated.append(copy)
    return updated if changed else profiles


def load_profiles() -> list[dict[str, Any]]:
    profiles = _read_json(PROFILES_PATH, [])
    if profiles:
        normalized = _attach_missing_preset_keys(profiles)
        merged = _merge_missing_defaults(normalized)
        if merged != profiles:
            save_profiles(merged)
        return merged
    save_profiles(default_profiles())
    return default_profiles()


def save_profiles(profiles: list[dict[str, Any]]) -> None:
    _write_json(PROFILES_PATH, profiles)


def reset_profiles() -> list[dict[str, Any]]:
    profiles = default_profiles()
    save_profiles(profiles)
    return profiles


def load_settings() -> dict[str, Any]:
    return _read_json(
        SETTINGS_PATH,
        {
            "last_device_address": "",
            "theme_mode": "auto",
            "theme": "dark",
            "window_width": 1320,
            "window_height": 860,
            "last_state": {
                "power": True,
                "brightness": 100,
                "speed": 60,
                "color": {"r": 88, "g": 182, "b": 255},
                "effect_code": 0,
            },
        },
    )


def save_settings(settings: dict[str, Any]) -> None:
    _write_json(SETTINGS_PATH, settings)

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from app.license import validate_license_state

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(user_data_dir("LumaBLE", False, roaming=True))
PROFILES_PATH = DATA_DIR / "profiles.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# Legacy source paths checked once during migration (oldest → newest order).
# "RGB" + "Controller" split keeps the old app name out of plain-text search.
def _legacy_migration_pairs() -> list[tuple[Path, Path]]:
    _old_app = "RGB" + "Controller"
    _old_app_dir = Path(user_data_dir(_old_app, False, roaming=True))
    _old_app_author_dir = Path(user_data_dir(_old_app, "dollza", roaming=True))
    _old_author_dir = Path(user_data_dir("LumaBLE", "dollza", roaming=True))
    _legacy_data_dir = APP_DIR / "data"
    return [
        (_old_app_author_dir / "profiles.json", PROFILES_PATH),
        (_old_app_author_dir / "settings.json", SETTINGS_PATH),
        (_old_app_dir / "profiles.json", PROFILES_PATH),
        (_old_app_dir / "settings.json", SETTINGS_PATH),
        (_old_author_dir / "profiles.json", PROFILES_PATH),
        (_old_author_dir / "settings.json", SETTINGS_PATH),
        (_legacy_data_dir / "profiles.json", PROFILES_PATH),
        (_legacy_data_dir / "settings.json", SETTINGS_PATH),
    ]

DEFAULT_PROFILES: list[dict[str, Any]] = [
    {
        "preset_key": "azure_drift",
        "name": "Azure Drift",
        "power": True,
        "brightness": 92,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 72, "g": 163, "b": 255},
    },
    {
        "preset_key": "neon_sunset",
        "name": "Neon Sunset",
        "power": True,
        "brightness": 88,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 255, "g": 106, "b": 56},
    },
    {
        "preset_key": "polar_mint",
        "name": "Polar Mint",
        "power": True,
        "brightness": 84,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 112, "g": 255, "b": 214},
    },
    {
        "preset_key": "violet_pulse",
        "name": "Violet Pulse",
        "power": True,
        "brightness": 86,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 170, "g": 96, "b": 255},
    },
    {
        "preset_key": "arctic_gold",
        "name": "Arctic Gold",
        "power": True,
        "brightness": 90,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 255, "g": 196, "b": 92},
    },
    {
        "preset_key": "pink_neon",
        "name": "Pink Neon",
        "power": True,
        "brightness": 87,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 255, "g": 92, "b": 168},
    },
    {
        "preset_key": "northern_sky",
        "name": "Northern Sky",
        "power": True,
        "brightness": 91,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 96, "g": 138, "b": 255},
    },
    {
        "preset_key": "moon_lavender",
        "name": "Moon Lavender",
        "power": True,
        "brightness": 85,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 198, "g": 166, "b": 255},
    },
    {
        "preset_key": "emerald_breeze",
        "name": "Emerald Breeze",
        "power": True,
        "brightness": 89,
        "speed": 60,
        "effect_code": 0,
        "color": {"r": 76, "g": 232, "b": 180},
    },
    {
        "preset_key": "amber_dawn",
        "name": "Amber Dawn",
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

DEFAULT_PROFILE_KEY_TO_NAME = {
    str(profile.get("preset_key", "")).strip(): str(profile.get("name", "")).strip()
    for profile in DEFAULT_PROFILES
    if str(profile.get("preset_key", "")).strip()
}

DEFAULT_START_COLOR = {"r": 88, "g": 182, "b": 255}
LEGACY_DARK_START_COLOR = {"r": 10, "g": 20, "b": 30}
CUSTOM_QUICK_MODE_MAX = 4

DEFAULT_SETTINGS: dict[str, Any] = {
    "last_device_address": "",
    "last_device_name": "",
    "color_history": [],
    "schedule": {
        "enabled": False,
        "on_time": "19:00",
        "off_time": "23:00",
        "startup_enabled": False,
        "days": [0, 1, 2, 3, 4, 5, 6],  # 0 = Monday .. 6 = Sunday
    },
    "theme_mode": "auto",
    "theme": "dark",
    "capture_compatibility": True,
    "ui_fps": "auto",
    "fade": True,
    "language": "ru",
    "ambient": {"region": "full", "saturation": 55, "smoothing": 65, "monitor": 0},
    "music": {
        "saturation": 60,
        "smoothing": 50,
        "speed": 30,
        "beat": 40,
        "device": "",
        "colors": {
            "bass": {"r": 255, "g": 80, "b": 70},
            "mid": {"r": 180, "g": 90, "b": 255},
            "treble": {"r": 60, "g": 190, "b": 255},
        },
    },
    "software_fx": {"effect": "breathing", "speed": 30},
    "app_triggers": {"enabled": False, "default": "", "rules": []},
    "quick_mode": "",
    "custom_quick_modes": [],
    "updates_last_auto_check_at": 0,
    "updates_notified_version": "",
    "license": {
        "activated": False,
        "edition": "free",
        "kind": "",
        "provider": "",
        "license_key": "",
        "license_id": "",
        "instance_id": "",
        "checked_at": "",
        "grace_days": 7,
    },
    "window_width": 1320,
    "window_height": 860,
    "last_state": {
        "power": True,
        "brightness": 100,
        "speed": 60,
        "color": DEFAULT_START_COLOR,
        "effect_code": 0,
    },
}


_migration_done: bool = False


def _run_migration() -> None:
    for source, target in _legacy_migration_pairs():
        if target.exists() or not source.exists():
            continue
        try:
            shutil.copy2(source, target)
        except OSError:
            pass


def _ensure_data_dir() -> None:
    global _migration_done
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _migration_done:
        _run_migration()
        _migration_done = True


def _read_json(path: Path, default: Any) -> Any:
    _ensure_data_dir()
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def validate_profile(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None

    preset_key = str(data.get("preset_key", "")).strip()
    name = str(data.get("name", "")).strip()
    if not preset_key and not name:
        return None
    if not preset_key:
        preset_key = DEFAULT_PROFILE_NAME_TO_KEY.get(name.lower(), "")
    if not name:
        name = DEFAULT_PROFILE_KEY_TO_NAME.get(preset_key, preset_key or "Profile")

    color = data.get("color", {})
    if not isinstance(color, dict):
        color = {}

    profile = {
        "preset_key": preset_key,
        "name": name,
        "power": _coerce_bool(data.get("power", True)),
        "brightness": _coerce_int(data.get("brightness"), 100, 0, 100),
        "speed": _coerce_int(data.get("speed"), 60, 0, 100),
        "effect_code": _coerce_int(data.get("effect_code"), 0, 0, 255),
        "color": {
            "r": _coerce_int(color.get("r"), 88, 0, 255),
            "g": _coerce_int(color.get("g"), 182, 0, 255),
            "b": _coerce_int(color.get("b"), 255, 0, 255),
        },
    }
    if "schedule" in data:
        profile["schedule"] = validate_schedule(data.get("schedule"))
    return profile


def validate_color_history(data: Any, *, limit: int = 12) -> list[dict[str, int]]:
    if not isinstance(data, list):
        return []
    colors: list[dict[str, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        color = (
            _coerce_int(item.get("r"), 0, 0, 255),
            _coerce_int(item.get("g"), 0, 0, 255),
            _coerce_int(item.get("b"), 0, 0, 255),
        )
        if color in seen:
            continue
        seen.add(color)
        colors.append({"r": color[0], "g": color[1], "b": color[2]})
        if len(colors) >= limit:
            break
    return colors


def _coerce_hex_color(value: Any, fallback: str) -> str:
    text = _coerce_str(value, fallback).lstrip("#")
    if len(text) != 6:
        return fallback
    try:
        int(text, 16)
    except ValueError:
        return fallback
    return f"#{text.lower()}"


def validate_custom_quick_modes(data: Any, *, limit: int = CUSTOM_QUICK_MODE_MAX) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    modes: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        profile = validate_profile(item)
        if profile is None:
            continue
        key = _coerce_str(item.get("key"), f"custom_{index}")
        if key in seen_keys:
            key = f"custom_{index}"
        seen_keys.add(key)
        profile["key"] = key
        source_profile_name = _coerce_str(item.get("source_profile_name"), "")
        if source_profile_name:
            profile["source_profile_name"] = source_profile_name
        profile["accent"] = _coerce_hex_color(item.get("accent"), "#7fb7ff")
        modes.append(profile)
        if len(modes) >= limit:
            break
    return modes


def _coerce_time_text(value: Any, default: str) -> str:
    text = _coerce_str(value, default)
    parts = text.split(":")
    if len(parts) != 2:
        return default
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return default
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return default
    return f"{hour:02d}:{minute:02d}"


def validate_ambient(data: Any) -> dict[str, Any]:
    defaults = DEFAULT_SETTINGS["ambient"]
    if not isinstance(data, dict):
        data = {}
    region = _coerce_str(data.get("region"), str(defaults["region"]))
    if region not in {"full", "center", "bottom", "top"}:
        region = str(defaults["region"])
    return {
        "region": region,
        "saturation": _coerce_int(data.get("saturation"), int(defaults["saturation"]), 0, 100),
        "smoothing": _coerce_int(data.get("smoothing"), int(defaults["smoothing"]), 0, 100),
        "monitor": _coerce_int(data.get("monitor"), int(defaults["monitor"]), 0, 15),
    }


def _coerce_rgb(value: Any, default: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        value = {}
    return {
        "r": _coerce_int(value.get("r"), int(default["r"]), 0, 255),
        "g": _coerce_int(value.get("g"), int(default["g"]), 0, 255),
        "b": _coerce_int(value.get("b"), int(default["b"]), 0, 255),
    }


def validate_music(data: Any) -> dict[str, Any]:
    defaults = DEFAULT_SETTINGS["music"]
    if not isinstance(data, dict):
        data = {}
    colors = data.get("colors") if isinstance(data.get("colors"), dict) else {}
    default_colors = defaults["colors"]
    return {
        "saturation": _coerce_int(data.get("saturation"), int(defaults["saturation"]), 0, 100),
        "smoothing": _coerce_int(data.get("smoothing"), int(defaults["smoothing"]), 0, 100),
        "speed": _coerce_int(data.get("speed"), int(defaults["speed"]), 0, 100),
        "beat": _coerce_int(data.get("beat"), int(defaults["beat"]), 0, 100),
        "device": _coerce_str(data.get("device"), str(defaults["device"])),
        "colors": {
            band: _coerce_rgb(colors.get(band), default_colors[band])
            for band in ("bass", "mid", "treble")
        },
    }


def validate_software_fx(data: Any) -> dict[str, Any]:
    defaults = DEFAULT_SETTINGS["software_fx"]
    if not isinstance(data, dict):
        data = {}
    effect = _coerce_str(data.get("effect"), str(defaults["effect"]))
    if effect not in {"breathing", "heartbeat", "rainbow", "candle", "storm", "gradient", "lava", "aurora"}:
        effect = str(defaults["effect"])
    return {
        "effect": effect,
        "speed": _coerce_int(data.get("speed"), int(defaults["speed"]), 0, 100),
    }


def validate_app_triggers(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    rules: list[dict[str, str]] = []
    raw_rules = data.get("rules", [])
    if isinstance(raw_rules, list):
        for item in raw_rules[:20]:
            if not isinstance(item, dict):
                continue
            app = _coerce_str(item.get("app"), "").strip()
            scene = _coerce_str(item.get("scene"), "").strip()
            if app and scene:
                rules.append({"app": app, "scene": scene})
    return {
        "enabled": _coerce_bool(data.get("enabled"), False),
        "default": _coerce_str(data.get("default"), "").strip(),
        "rules": rules,
    }


def _coerce_days(value: Any, default: list[int]) -> list[int]:
    if not isinstance(value, list):
        return list(default)
    return sorted({int(d) for d in value if isinstance(d, (int, float)) and 0 <= int(d) <= 6})


def validate_schedule(data: Any) -> dict[str, Any]:
    defaults = DEFAULT_SETTINGS["schedule"]
    if not isinstance(data, dict):
        data = {}
    return {
        "enabled": _coerce_bool(data.get("enabled"), bool(defaults["enabled"])),
        "on_time": _coerce_time_text(data.get("on_time"), str(defaults["on_time"])),
        "off_time": _coerce_time_text(data.get("off_time"), str(defaults["off_time"])),
        "startup_enabled": _coerce_bool(data.get("startup_enabled"), bool(defaults["startup_enabled"])),
        "days": _coerce_days(data.get("days"), list(defaults["days"])),
    }


def validate_settings(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}

    raw_theme_mode = str(data.get("theme_mode") or data.get("theme") or DEFAULT_SETTINGS["theme_mode"]).strip().lower()
    theme_mode = raw_theme_mode if raw_theme_mode in {"dark", "light", "auto"} else DEFAULT_SETTINGS["theme_mode"]
    raw_theme = str(data.get("theme") or "").strip().lower()
    theme = raw_theme if raw_theme in {"dark", "light"} else ("dark" if theme_mode == "dark" else "light")

    last_state = data.get("last_state", {})
    if not isinstance(last_state, dict):
        last_state = {}
    color = last_state.get("color", {})
    if not isinstance(color, dict):
        color = {}

    language = _coerce_str(data.get("language"), DEFAULT_SETTINGS["language"])
    quick_mode = _coerce_str(data.get("quick_mode"), DEFAULT_SETTINGS["quick_mode"])
    custom_quick_modes = validate_custom_quick_modes(data.get("custom_quick_modes", DEFAULT_SETTINGS["custom_quick_modes"]))
    capture_compatibility = _coerce_bool(
        data.get("capture_compatibility"),
        bool(DEFAULT_SETTINGS["capture_compatibility"]),
    )
    ui_fps = _coerce_str(data.get("ui_fps"), str(DEFAULT_SETTINGS["ui_fps"])).lower()
    if ui_fps not in {"auto", "30", "60", "120"}:
        ui_fps = str(DEFAULT_SETTINGS["ui_fps"])
    last_device_address = _coerce_str(data.get("last_device_address"), DEFAULT_SETTINGS["last_device_address"])
    last_device_name = _coerce_str(data.get("last_device_name"), DEFAULT_SETTINGS["last_device_name"])
    color_history = validate_color_history(data.get("color_history", DEFAULT_SETTINGS["color_history"]))
    schedule = validate_schedule(data.get("schedule", DEFAULT_SETTINGS["schedule"]))

    parsed_last_color = {
        "r": _coerce_int(color.get("r"), DEFAULT_START_COLOR["r"], 0, 255),
        "g": _coerce_int(color.get("g"), DEFAULT_START_COLOR["g"], 0, 255),
        "b": _coerce_int(color.get("b"), DEFAULT_START_COLOR["b"], 0, 255),
    }
    parsed_last_brightness = _coerce_int(last_state.get("brightness"), 100, 0, 100)
    if parsed_last_color == LEGACY_DARK_START_COLOR and parsed_last_brightness <= 40:
        parsed_last_color = dict(DEFAULT_START_COLOR)
        parsed_last_brightness = 100

    return {
        "last_device_address": last_device_address,
        "last_device_name": last_device_name,
        "color_history": color_history,
        "schedule": schedule,
        "theme_mode": theme_mode,
        "theme": theme,
        "capture_compatibility": capture_compatibility,
        "ui_fps": ui_fps,
        "fade": _coerce_bool(data.get("fade"), bool(DEFAULT_SETTINGS["fade"])),
        "language": language,
        "ambient": validate_ambient(data.get("ambient", DEFAULT_SETTINGS["ambient"])),
        "music": validate_music(data.get("music", DEFAULT_SETTINGS["music"])),
        "software_fx": validate_software_fx(data.get("software_fx", DEFAULT_SETTINGS["software_fx"])),
        "app_triggers": validate_app_triggers(data.get("app_triggers", DEFAULT_SETTINGS["app_triggers"])),
        "quick_mode": quick_mode,
        "custom_quick_modes": custom_quick_modes,
        "updates_last_auto_check_at": _coerce_int(
            data.get("updates_last_auto_check_at"),
            DEFAULT_SETTINGS["updates_last_auto_check_at"],
            0,
            4_102_444_800,
        ),
        "updates_notified_version": _coerce_str(
            data.get("updates_notified_version"),
            DEFAULT_SETTINGS["updates_notified_version"],
        ),
        "license": validate_license_state(data.get("license", DEFAULT_SETTINGS["license"])),
        "window_width": _coerce_int(data.get("window_width"), DEFAULT_SETTINGS["window_width"], 800, 7680),
        "window_height": _coerce_int(data.get("window_height"), DEFAULT_SETTINGS["window_height"], 600, 4320),
        "last_state": {
            "power": _coerce_bool(last_state.get("power", True)),
            "brightness": parsed_last_brightness,
            "speed": _coerce_int(last_state.get("speed"), 60, 0, 100),
            "effect_code": _coerce_int(last_state.get("effect_code"), 0, 0, 255),
            "color": parsed_last_color,
        },
    }


def _validate_profiles(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, list):
        return [], 0
    profiles: list[dict[str, Any]] = []
    skipped = 0
    for entry in payload:
        profile = validate_profile(entry)
        if profile is None:
            skipped += 1
            continue
        profiles.append(profile)
    return profiles, skipped


def validate_profiles_payload(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if isinstance(payload, dict) and isinstance(payload.get("profiles"), list):
        payload = payload["profiles"]
    return _validate_profiles(payload)


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
    raw_profiles = _read_json(PROFILES_PATH, [])
    profiles, skipped = _validate_profiles(raw_profiles)
    if profiles:
        normalized = _attach_missing_preset_keys(profiles)
        merged = _merge_missing_defaults(normalized)
        if skipped or merged != raw_profiles:
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


def detect_system_language(default: str = "en") -> str:
    """Best-effort map the OS UI language to a bundled app language.

    Only used on the very first launch (no settings file yet) so the app opens
    in the user's system language — e.g. English Windows -> English. Unknown
    locales fall back to ``default`` (English, the safe lingua franca).
    """
    primary = ""
    try:
        from PySide6.QtCore import QLocale

        primary = QLocale.system().name().split("_")[0].strip().lower()
    except Exception:  # detection is best-effort; any failure -> fallback
        primary = ""
    if not primary:
        try:
            import locale

            primary = (locale.getlocale()[0] or "").split("_")[0].strip().lower()
        except Exception:
            primary = ""
    try:
        from app.localization import localization_manager

        available = set(localization_manager.available_languages())
    except Exception:
        available = {"ru", "en", "es", "zh"}
    if primary in available:
        return primary
    return default if default in available else "en"


def load_settings() -> dict[str, Any]:
    _ensure_data_dir()
    first_run = not SETTINGS_PATH.exists()
    raw_settings = _read_json(SETTINGS_PATH, DEFAULT_SETTINGS)
    settings = validate_settings(raw_settings)
    if first_run:
        settings["language"] = detect_system_language()
    if settings != raw_settings:
        save_settings(settings)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    _write_json(SETTINGS_PATH, settings)

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from app.automation.file_lock import file_lock
from app.automation.rules import rule_to_dict, validate_rules
from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.device_names import validate_device_names, validate_extra_addresses
from app.hotkeys import ACTIONS as HOTKEY_ACTIONS
from app.hotkeys import DEFAULT_HOTKEYS, parse_hotkey
from app.license import validate_license_state
from app.local_api.config import validate_api_settings
from app.motion_policy import DEFAULT_MOTION_MODE, normalize_motion_mode
from app.scene_store import normalize_group
from app.scenes import is_future_scene_envelope, normalize_scene, unwrap_scene, wrap_scene
from app.screen_profiles import normalize_profile_id

APP_DIR = Path(__file__).resolve().parent.parent
# Where the settings live. ``LUMABLE_DATA_DIR`` moves them, which is what makes
# the test suite safe: an environment variable is inherited by child processes,
# and patching a module attribute is not. A subprocess helper that builds a
# window would otherwise reach the real installation however carefully the
# parent had redirected itself.
DATA_DIR = Path(os.environ.get("LUMABLE_DATA_DIR") or user_data_dir("LumaBLE", False, roaming=True))
PROFILES_PATH = DATA_DIR / "profiles.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# More rules than this and every tick would spend its time on a list no user
# authored. Capped at the persistence boundary, exactly like scenes.
MAX_AUTOMATION_RULES = 100

# Long enough to outlast another process's write, short enough that a stuck lock
# does not hold up the app: settings writes are milliseconds of work.
SETTINGS_LOCK_TIMEOUT_SECONDS = 5.0


def automation_journal_path() -> Path:
    """Where the automation journal lives.

    A function rather than a module constant so it follows ``DATA_DIR`` when that
    is redirected — a constant would bind the developer's real directory at import
    time and a test would write its journal there.
    """
    return DATA_DIR / "automation-journal.json"


def automation_tasks_path() -> Path:
    """What the Windows task compiler last put on the machine.

    Its own file rather than a corner of the automation state: the state belongs to
    whichever process is *running* automations, this belongs to whichever process
    last *compiled* them, and neither should have to take the other's lock. Losing
    it costs one round of "update everything", never a wrong task.
    """
    return DATA_DIR / "automation-tasks.json"


def automation_migration_backup_path() -> Path:
    """The settings and profiles as they were before the first migration.

    Written once and never overwritten: a second migration must not replace the
    original with a copy of the already-migrated state, which is precisely what
    someone reaching for a backup would not want to find.
    """
    return DATA_DIR / "pre-automation-migration.json"


def automation_control_path() -> Path:
    """What the user has asked automations to do: at the moment, whether to pause.

    Deliberately not part of the automation state. That file is guarded by the
    execution lock, which is held for the whole length of a run — connect, write,
    tear down — so an intent recorded there could be waiting on a BLE command to
    finish. This one has a lock of its own that is never held for more than a small
    write, which is what makes "pause" something the machine hears at once and keeps
    hearing after the app that asked has closed.
    """
    return DATA_DIR / "automation-control.json"


def automation_state_path() -> Path:
    """Which rule occurrences have already been handled, and when each last ran.

    Separate from settings: it is bookkeeping the app writes for itself, and a
    corrupt state file must cost at most one duplicate run — never the user's
    configuration. A function for the same reason as the journal path above.
    """
    return DATA_DIR / "automation-state.json"

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
    "color_temperature": 4500,
    "language": "ru",
    "ambient": {"region": "full", "saturation": 55, "smoothing": 65, "monitor": 0, "profile": "desktop"},
    "fusion": {"mode": "screen"},
    "music": {
        "saturation": 60,
        "smoothing": 50,
        "speed": 30,
        "beat": 40,
        "gate": 16,
        "source": "system",
        "device": "",
        "mic_device": "",
        "colors": {
            "bass": {"r": 255, "g": 80, "b": 70},
            "mid": {"r": 180, "g": 90, "b": 255},
            "treble": {"r": 60, "g": 190, "b": 255},
        },
    },
    "software_fx": {"effect": "breathing", "speed": 30},
    "app_triggers": {"enabled": False, "default": "", "rules": []},
    # 0.3.6 automations. Kept beside the old schedule and app_triggers blocks
    # rather than replacing them: a user who rolls back to 0.3.5 must still find
    # their schedule where that build looks for it.
    "automations": {
        "enabled": False,
        "rules": [],
        "migrated_version": 0,
        "legacy_bridge": False,
        "legacy_cleanup_pending": False,
        "preset_scenes": {},
    },
    "hotkeys": {"enabled": False, "bindings": dict(DEFAULT_HOTKEYS)},
    "diy": {
        "steps": [
            {"rgb": [255, 77, 77], "duration_ms": 1000},
            {"rgb": [91, 140, 255], "duration_ms": 1000},
        ],
        "transition": "smooth",
        "speed": 50,
    },
    "diy_saved": [],
    "timers": {
        "sleep_minutes": 30,
        "sunrise_minutes": 20,
        "sunrise_time": "07:00",
        "sunrise_color": {"r": 255, "g": 180, "b": 120},
        "sunrise_armed": False,
    },
    "onboarding_seen": False,
    "device_names": {},
    # Extra strips the user added, so a multi-strip setup (and the groups and
    # scenes built on it) survives a restart instead of silently shrinking.
    "extra_device_addresses": [],
    "scenes": [],
    "device_groups": [],
    "api": {
        "enabled": False,
        "port": 7345,
        "token": "",
        "allow_lan": False,
        "lan_confirmed": False,
        "lan_warning_count": 0,
        "lan_host": "",
    },
    "quick_mode": "",
    "custom_quick_modes": [],
    "updates_last_auto_check_at": 0,
    "updates_last_auto_check_version": "",
    "updates_notified_version": "",
    "updates_notified_at": 0,
    "updates_skipped_version": "",
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
    "motion_mode": DEFAULT_MOTION_MODE,
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


def validate_fusion(data: Any) -> dict[str, Any]:
    """What the strip follows: the screen alone, or the screen with the music.

    A choice the user made on the card, so it has to survive a restart like any
    other. Anything unrecognised falls back to the screen — the mode that needs
    nothing beyond what Screen Sync already needs.
    """
    defaults = DEFAULT_SETTINGS["fusion"]
    if not isinstance(data, dict):
        data = {}
    mode = _coerce_str(data.get("mode"), str(defaults["mode"]))
    if mode not in {"screen", "screen_music"}:
        mode = str(defaults["mode"])
    return {"mode": mode}


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
        "profile": normalize_profile_id(data.get("profile", defaults.get("profile"))),
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
        "gate": _coerce_int(data.get("gate"), int(defaults["gate"]), 0, 100),
        "source": "mic" if str(data.get("source", "system")) == "mic" else "system",
        "device": _coerce_str(data.get("device"), str(defaults["device"])),
        "mic_device": _coerce_str(data.get("mic_device"), str(defaults["mic_device"])),
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


def validate_hotkeys(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    raw = data.get("bindings", {})
    raw = raw if isinstance(raw, dict) else {}
    bindings: dict[str, str] = {}
    for action in HOTKEY_ACTIONS:
        spec = _coerce_str(raw.get(action), DEFAULT_HOTKEYS[action]).strip()
        # Keep a usable combo: fall back to the default if the saved spec is junk.
        bindings[action] = spec if parse_hotkey(spec) is not None else DEFAULT_HOTKEYS[action]
    return {
        "enabled": _coerce_bool(data.get("enabled"), False),
        "bindings": bindings,
    }


def validate_diy(data: Any) -> dict[str, Any]:
    from app.diy_effects import MAX_STEPS, MOTION_KEYS

    if not isinstance(data, dict):
        data = {}
    steps: list[dict[str, Any]] = []
    raw_steps = data.get("steps", [])
    if isinstance(raw_steps, list):
        for item in raw_steps[:MAX_STEPS]:
            if not isinstance(item, dict):
                continue
            rgb = item.get("rgb", [255, 255, 255])
            rgb = rgb if isinstance(rgb, (list, tuple)) and len(rgb) == 3 else [255, 255, 255]
            motion = _coerce_str(item.get("motion"), "none")
            if motion not in MOTION_KEYS:
                motion = "none"
            steps.append({
                "rgb": [_coerce_int(rgb[0], 255, 0, 255), _coerce_int(rgb[1], 255, 0, 255), _coerce_int(rgb[2], 255, 0, 255)],
                "duration_ms": _coerce_int(item.get("duration_ms"), 1000, 0, 10_000),
                "motion": motion,
            })
    if len(steps) < 2:
        steps = [
            {"rgb": [255, 77, 77], "duration_ms": 1000},
            {"rgb": [91, 140, 255], "duration_ms": 1000},
        ]
    transition = "cut" if str(data.get("transition", "smooth")) == "cut" else "smooth"
    return {
        "steps": steps,
        "transition": transition,
        "speed": _coerce_int(data.get("speed"), 50, 0, 100),
    }


def validate_diy_saved(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data[:8]:
        if not isinstance(item, dict):
            continue
        name = _coerce_str(item.get("name"), "").strip()[:40]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        effect = validate_diy(item)
        out.append({"name": name, **effect})
    return out


def validate_timers(data: Any) -> dict[str, Any]:
    defaults = DEFAULT_SETTINGS["timers"]
    if not isinstance(data, dict):
        data = {}
    return {
        "sleep_minutes": _coerce_int(data.get("sleep_minutes"), int(defaults["sleep_minutes"]), 1, 120),
        "sunrise_minutes": _coerce_int(data.get("sunrise_minutes"), int(defaults["sunrise_minutes"]), 1, 120),
        "sunrise_time": _coerce_time_text(data.get("sunrise_time"), str(defaults["sunrise_time"])),
        "sunrise_color": _coerce_rgb(data.get("sunrise_color"), defaults["sunrise_color"]),
        "sunrise_armed": _coerce_bool(data.get("sunrise_armed"), False),
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


def validate_automations(data: Any, warnings: list[str] | None = None) -> dict[str, Any]:
    """The automations block: a master switch and the rule list.

    Rules go through ``app.automation.rules``, which never raises and drops only
    what it cannot coerce — so one hand-edited rule costs that rule, not the rest
    of them. Pass ``warnings`` to learn what was quietly adjusted (see the WARN_*
    codes there), for instance a background rule downgraded to runtime.
    """
    defaults = DEFAULT_SETTINGS["automations"]
    if not isinstance(data, dict):
        data = {}
    rules = validate_rules(data.get("rules", []), warnings)[:MAX_AUTOMATION_RULES]
    return {
        "enabled": _coerce_bool(data.get("enabled"), bool(defaults["enabled"])),
        # Written back in canonical form: a rule read from disk and saved again
        # must not drift in shape, or the next build's migration reads two.
        "rules": [rule_to_dict(rule) for rule in rules],
        # Which migration has already run. Losing this would run it again, so it is
        # part of the validated shape rather than an incidental key.
        "migrated_version": _coerce_int(data.get("migrated_version"), 0, 0, 1000),
        # True while the 0.3.5 schedule tasks are still the executor for the rules
        # migrated from them — see app.automation.migration.
        "legacy_bridge": _coerce_bool(data.get("legacy_bridge"), False),
        # The handoff has been recorded but the old pair is not off the machine yet.
        # Written before the removal is attempted, so a removal that fails is
        # something the next start can finish.
        "legacy_cleanup_pending": _coerce_bool(data.get("legacy_cleanup_pending"), False),
        # Which scene the migration made for each built-in preset. Kept so ownership
        # of those scenes is something recorded rather than guessed from an id.
        "preset_scenes": _coerce_preset_scenes(data.get("preset_scenes")),
    }


def _coerce_preset_scenes(data: Any) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    mapping: dict[str, str] = {}
    for key, value in list(data.items())[:MAX_AUTOMATION_RULES]:
        preset, scene_id = str(key).strip(), str(value).strip()
        if preset and scene_id:
            mapping[preset] = scene_id
    return mapping


def validate_scenes(data: Any) -> list[dict[str, Any]]:
    """Keep known scenes canonical and intact future scenes opaque.

    A newer envelope cannot be shown or applied safely, but dropping it here
    means an older application erases it on its next ordinary settings save.
    Corrupt envelopes are still discarded, and the shared cap still applies.
    """
    if not isinstance(data, list):
        return []
    scenes: list[dict[str, Any]] = []
    for entry in data:
        scene = unwrap_scene(entry)
        if scene is None and isinstance(entry, dict) and "state" in entry:
            scene = normalize_scene(entry)
        if scene is not None:
            scenes.append(wrap_scene(scene))
        elif is_future_scene_envelope(entry):
            # JSON data is treated as opaque: do not canonicalise a schema this
            # build does not understand and cannot promise to reproduce.
            scenes.append(json.loads(json.dumps(entry)))
        if len(scenes) >= 50:
            break
    return scenes


def validate_device_groups(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in data:
        group = normalize_group(entry)
        if group and group["name"] and group["group_id"] not in seen:
            seen.add(group["group_id"])
            groups.append(group)
    return groups


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
        "onboarding_seen": _coerce_bool(data.get("onboarding_seen"), bool(DEFAULT_SETTINGS["onboarding_seen"])),
        "color_temperature": _coerce_int(data.get("color_temperature"), 4500, 2000, 6500),
        "language": language,
        "ambient": validate_ambient(data.get("ambient", DEFAULT_SETTINGS["ambient"])),
        "fusion": validate_fusion(data.get("fusion", DEFAULT_SETTINGS["fusion"])),
        "music": validate_music(data.get("music", DEFAULT_SETTINGS["music"])),
        "software_fx": validate_software_fx(data.get("software_fx", DEFAULT_SETTINGS["software_fx"])),
        "app_triggers": validate_app_triggers(data.get("app_triggers", DEFAULT_SETTINGS["app_triggers"])),
        "automations": validate_automations(data.get("automations", DEFAULT_SETTINGS["automations"])),
        "hotkeys": validate_hotkeys(data.get("hotkeys", DEFAULT_SETTINGS["hotkeys"])),
        "diy": validate_diy(data.get("diy", DEFAULT_SETTINGS["diy"])),
        "diy_saved": validate_diy_saved(data.get("diy_saved", [])),
        "timers": validate_timers(data.get("timers", DEFAULT_SETTINGS["timers"])),
        "device_names": validate_device_names(data.get("device_names", DEFAULT_SETTINGS["device_names"])),
        "extra_device_addresses": validate_extra_addresses(data.get("extra_device_addresses", [])),
        "scenes": validate_scenes(data.get("scenes", [])),
        "device_groups": validate_device_groups(data.get("device_groups", [])),
        "api": validate_api_settings(data.get("api", DEFAULT_SETTINGS["api"])),
        "quick_mode": quick_mode,
        "custom_quick_modes": custom_quick_modes,
        "updates_last_auto_check_at": _coerce_int(
            data.get("updates_last_auto_check_at"),
            DEFAULT_SETTINGS["updates_last_auto_check_at"],
            0,
            4_102_444_800,
        ),
        "updates_last_auto_check_version": _coerce_str(
            data.get("updates_last_auto_check_version"),
            DEFAULT_SETTINGS["updates_last_auto_check_version"],
        ),
        "updates_notified_version": _coerce_str(
            data.get("updates_notified_version"),
            DEFAULT_SETTINGS["updates_notified_version"],
        ),
        "updates_notified_at": _coerce_int(
            data.get("updates_notified_at"),
            DEFAULT_SETTINGS["updates_notified_at"],
            0,
            4_102_444_800,
        ),
        "updates_skipped_version": _coerce_str(
            data.get("updates_skipped_version"),
            DEFAULT_SETTINGS["updates_skipped_version"],
        ),
        "license": validate_license_state(data.get("license", DEFAULT_SETTINGS["license"])),
        # Lower bounds track the window minimum, so a small window a user chose
        # on a 1366×768@150% screen survives a restart instead of snapping back
        # up to 800×600 (which would reopen larger than that screen).
        "window_width": _coerce_int(data.get("window_width"), DEFAULT_SETTINGS["window_width"], WINDOW_MIN_WIDTH, 7680),
        "window_height": _coerce_int(data.get("window_height"), DEFAULT_SETTINGS["window_height"], WINDOW_MIN_HEIGHT, 4320),
        "motion_mode": normalize_motion_mode(data.get("motion_mode", DEFAULT_MOTION_MODE)),
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
    """Write through a temporary file, so a reader never sees half a file.

    The temporary name carries this process's id: a headless automation run and the
    open app write the same settings file, and one shared ``.tmp`` name would let
    them rename each other's half-written content into place.
    """
    _ensure_data_dir()
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - nothing more we can do
            pass
        raise


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


# Set once a restore has replaced the settings file. Every ordinary write is a
# snapshot of the world that existed before the restore, and this process is on
# its way out — the shutdown path alone saves settings from three different
# controllers, any one of which would put the old scenes back. A flag on the
# window would not stop them; it has to live where the writing happens.
_writes_frozen = False


def freeze_settings_writes() -> None:
    """Refuse further ordinary writes for the rest of this process."""
    global _writes_frozen
    _writes_frozen = True


def settings_writes_frozen() -> bool:
    return _writes_frozen


def restore_settings_file(payload: dict[str, Any]) -> Path | None:
    """Replace the settings file with a restored one, then freeze writing.

    The safety copy, the replacement and the freeze all happen inside one hold
    of the settings lock, so nothing in this process can write between them —
    a second handle on that lock waits for the one already held. Returns where
    the previous settings were kept, or ``None`` if there were none.

    This is the one path that writes while frozen; it is what does the freezing.
    """
    global _writes_frozen
    with file_lock(_settings_lock_path(), timeout=SETTINGS_LOCK_TIMEOUT_SECONDS) as locked:
        if not locked:
            raise TimeoutError("settings file is busy")
        kept: Path | None = None
        if SETTINGS_PATH.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            kept = SETTINGS_PATH.with_name(f"settings-before-restore-{stamp}.json")
            shutil.copy2(SETTINGS_PATH, kept)
        # If this raises, the freeze below never happens and the app carries on
        # with what it had — which is the whole point of doing it in this order.
        _write_json(SETTINGS_PATH, json.loads(json.dumps(payload)))
        _writes_frozen = True
        return kept


def save_settings(settings: dict[str, Any]) -> None:
    if _writes_frozen:
        # A restore has already replaced the file. This snapshot describes the
        # world before it, and writing it back is exactly the accident the
        # freeze exists to prevent.
        return
    with file_lock(_settings_lock_path(), timeout=SETTINGS_LOCK_TIMEOUT_SECONDS) as locked:
        if not locked:
            raise TimeoutError("settings file is busy")

        payload = json.loads(json.dumps(settings))
        if SETTINGS_PATH.exists():
            # Power is runtime state shared with the headless automation process.
            # Most callers save an old, long-lived settings snapshot after changing
            # an unrelated field; letting that snapshot own power would undo a
            # background command that completed in the meantime. Actual power
            # commands use update_power_setting() below.
            current = validate_settings(_read_json(SETTINGS_PATH, DEFAULT_SETTINGS))
            payload.setdefault("last_state", {})["power"] = current["last_state"]["power"]
        _write_json(SETTINGS_PATH, payload)


def update_settings(mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Change a few keys of the stored settings, without a stale full snapshot.

    Read and write happen inside one lock, so a headless automation run that only
    wants to record the new power state cannot overwrite everything the open app
    has changed in the meantime. ``mutate`` is handed the freshly read settings and
    must touch only the keys it owns.

    Deliberately built on the low-level read/write rather than
    ``load_settings``/``save_settings``: those take the same lock, and a second
    handle on it in this process would wait for the one we are already holding.
    """
    if _writes_frozen:
        return validate_settings(_read_json(SETTINGS_PATH, DEFAULT_SETTINGS))
    with file_lock(_settings_lock_path(), timeout=SETTINGS_LOCK_TIMEOUT_SECONDS) as locked:
        if not locked:
            raise TimeoutError("settings file is busy")
        settings = validate_settings(_read_json(SETTINGS_PATH, DEFAULT_SETTINGS))
        mutate(settings)
        _write_json(SETTINGS_PATH, settings)
        return settings


def update_power_setting(enabled: bool) -> dict[str, Any]:
    """Persist a power command without exposing it to stale full snapshots."""

    power = bool(enabled)

    def set_power(settings: dict[str, Any]) -> None:
        settings.setdefault("last_state", {})["power"] = power

    return update_settings(set_power)


def _settings_lock_path() -> Path:
    return SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".lock")

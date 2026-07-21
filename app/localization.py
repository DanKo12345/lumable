from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from app.storage import DATA_DIR

L10N_PREFIX = "__L10N__"
L10N_SUFFIX = "__END__"

LANGUAGE_ORDER: tuple[str, ...] = ("ru", "en", "es", "zh")
I18N_PACKAGE = "app.i18n"
USER_I18N_DIR = DATA_DIR / "i18n"


def _extract_language_payload(payload: Any, fallback_code: str) -> tuple[str, str, dict[str, str]] | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("language", {})
    translations = payload.get("translations", {})
    if not isinstance(meta, dict) or not isinstance(translations, dict):
        return None
    code = str(meta.get("code") or fallback_code).strip()
    label = str(meta.get("label") or code).strip()
    if not code:
        return None
    clean_translations = {str(key): str(value) for key, value in translations.items()}
    return code, label, clean_translations


def _load_i18n_file(path: Path, fallback_code: str) -> tuple[str, str, dict[str, str]] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _extract_language_payload(payload, fallback_code)


def _load_packaged_i18n() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    translations: dict[str, dict[str, str]] = {}
    labels: dict[str, str] = {}
    try:
        files = resources.files(I18N_PACKAGE)
    except ModuleNotFoundError:
        return translations, labels
    for resource in files.iterdir():
        if resource.name.startswith("_") or resource.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parsed = _extract_language_payload(payload, resource.stem)
        if parsed is None:
            continue
        code, label, bundle = parsed
        translations[code] = bundle
        labels[code] = label
    return translations, labels


def _load_user_i18n() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    translations: dict[str, dict[str, str]] = {}
    labels: dict[str, str] = {}
    if not USER_I18N_DIR.exists():
        return translations, labels
    for path in USER_I18N_DIR.glob("*.json"):
        parsed = _load_i18n_file(path, path.stem)
        if parsed is None:
            continue
        code, label, bundle = parsed
        translations[code] = bundle
        labels[code] = label
    return translations, labels


def _load_i18n() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    translations, labels = _load_packaged_i18n()
    user_translations, user_labels = _load_user_i18n()
    for code, bundle in user_translations.items():
        base = dict(translations.get(code, {}))
        base.update(bundle)
        translations[code] = base
    labels.update(user_labels)
    return translations, labels


class LocalizationManager:
    def __init__(self) -> None:
        self._translations, self._language_labels = _load_i18n()
        self._language = "ru" if "ru" in self._translations else next(iter(self._translations), "ru")

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        self._language = language if language in self._translations else "ru"

    def reload(self) -> None:
        current_language = self._language
        self._translations, self._language_labels = _load_i18n()
        self.set_language(current_language)

    def t(self, key: str, **kwargs: Any) -> str:
        bundle = self._translations.get(self._language, {})
        fallback = self._translations.get("ru", {})
        template = bundle.get(key) or fallback.get(key) or key
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template

    def available_languages(self) -> list[str]:
        ordered = [language for language in LANGUAGE_ORDER if language in self._translations]
        extra = sorted(language for language in self._translations if language not in LANGUAGE_ORDER)
        return ordered + extra

    def language_name(self, language: str) -> str:
        return self._language_labels.get(language, language)

    def translation_variants(self, key: str) -> list[str]:
        variants: list[str] = []
        for bundle in self._translations.values():
            value = bundle.get(key)
            if value and value not in variants:
                variants.append(value)
        return variants

    def effect_name(self, effect_key: str) -> str:
        return self.t(f"effect.{effect_key}")

    def profile_name(self, profile: dict[str, Any]) -> str:
        preset_key = str(profile.get("preset_key", "")).strip()
        if preset_key:
            return self.t(f"profile.{preset_key}")
        return str(profile.get("name", "")).strip()

    def profile_key_from_name(self, name: str) -> str:
        normalized = str(name).strip().casefold()
        if not normalized:
            return ""
        for bundle in self._translations.values():
            for key, value in bundle.items():
                if key.startswith("profile.") and str(value).strip().casefold() == normalized:
                    return key.removeprefix("profile.")
        return ""

    def status_config_event(self, action: str, profile: dict[str, Any] | None = None, *, name: str | None = None) -> str:
        payload = {
            "kind": "config",
            "action": action,
            "preset_key": str((profile or {}).get("preset_key", "")).strip(),
            "name": str(name).strip() if name is not None else str((profile or {}).get("name", "")).strip(),
        }
        return L10N_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + L10N_SUFFIX

    def status_ble_event(self, event: str, **payload: Any) -> str:
        data = {"kind": "ble", "event": event, **payload}
        return L10N_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + L10N_SUFFIX

    def _format_ble_error(self, message: str) -> str:
        prefix = self.t("error.ble_prefix")
        normalized = self.normalize_error_message(message).strip()
        if not normalized:
            return prefix.rstrip()
        if prefix.endswith((" ", "\n", "\uff1a")):
            return f"{prefix}{normalized}"
        return f"{prefix} {normalized}"

    def normalize_error_message(self, message: str) -> str:
        lower = message.lower()
        if (
            "bluetooth radio is not powered on" in lower
            or "bleakbluetoothnotavailableerror" in lower
            or "bluetoothnotavailableerror" in lower
            or "bluetooth adapter is disabled" in lower
            or "bluetooth is disabled" in lower
            or "bluetooth is turned off" in lower
            or "no bluetooth adapters" in lower
            or ("bluetooth" in lower and "not available" in lower)
            or ("bluetooth" in lower and "powered off" in lower)
        ):
            return self.t("error.bluetooth_off")
        if "connect to the led strip first" in lower:
            return self.t("error.connect_strip_first")
        if "device not found. make sure it is powered on and nearby." in lower:
            return self.t("error.device_not_found")
        if "no writable gatt characteristic was found on this device." in lower:
            return self.t("error.no_writable_gatt")
        if "no supported controller protocol was detected on this device." in lower:
            return self.t("error.protocol_not_supported")
        if "built-in effects are not supported by this controller yet." in lower:
            return self.t("error.effects_not_supported")
        if "command could not be written to any compatible gatt characteristic." in lower:
            return self.t("error.write_failed")
        if "device was found and matched a known controller family, but the command protocol differs" in lower:
            return self.t("error.protocol_mismatch")
        if "command could not be sent with any known protocol." in lower:
            return self.t("error.unknown_protocol_send")
        return message

    def normalize_status_message(self, message: str) -> str:
        if message.startswith(L10N_PREFIX):
            result = self._normalize_structured(message)
            if result is not None:
                return result
        return self._normalize_legacy(message)

    # ── structured L10N payload ────────────────────────────────────────

    def _normalize_structured(self, message: str) -> str | None:
        suffix_index = message.find(L10N_SUFFIX)
        remainder = "" if suffix_index == -1 else message[suffix_index + len(L10N_SUFFIX):]
        if suffix_index == -1:
            suffix_index = len(message)
        try:
            payload = json.loads(message[len(L10N_PREFIX):suffix_index])
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        kind = payload.get("kind")
        if kind == "config":
            return self._normalize_config_payload(payload, remainder)
        if kind == "ble":
            return self._normalize_ble_payload(payload, remainder)
        return None

    def _normalize_config_payload(self, payload: dict, remainder: str) -> str | None:
        action = str(payload.get("action", "")).strip().lower()
        preset_key = str(payload.get("preset_key", "")).strip()
        raw_name = str(payload.get("name", "")).strip()
        display_name = self.t(f"profile.{preset_key}") if preset_key else raw_name
        if action == "saved":
            return self.t("status.config_saved", name=display_name) + remainder
        if action == "loaded":
            return self.t("status.config_loaded", name=display_name) + remainder
        if action == "deleted":
            return self.t("status.config_deleted", name=display_name) + remainder
        return None

    def _normalize_ble_payload(self, payload: dict, remainder: str) -> str | None:  # noqa: C901
        event = str(payload.get("event", "")).strip()
        t = self.t

        def addr() -> str:
            return str(payload.get("address", "")).strip()

        def val() -> int:
            return int(payload.get("value", 0))

        if event == "scan_start":
            return t("status.ble.scan_start") + remainder
        if event == "scan_finished_none":
            return t("status.ble.scan_finished_none") + remainder
        if event == "scan_finished_found":
            return t("status.ble.scan_finished_found", count=int(payload.get("count", 0))) + remainder
        if event == "scan_finished_unknown":
            return t("status.ble.scan_finished_unknown", count=int(payload.get("count", 0))) + remainder
        if event == "mirror_added":
            return t("status.ble.mirror_added", name=str(payload.get("name", "")).strip(), address=addr()) + remainder
        if event == "mirror_removed":
            return t("status.ble.mirror_removed", address=addr()) + remainder
        if event == "mirror_lost":
            return t("status.ble.mirror_lost", address=addr()) + remainder
        if event == "mirror_unavailable":
            return t("status.ble.mirror_unavailable", address=addr()) + remainder
        if event == "primary_changed":
            return t("status.ble.primary_changed", name=str(payload.get("name", "")).strip(), address=addr()) + remainder
        if event in {"primary_changed_kept", "primary_changed_dropped"}:
            return (
                t(
                    f"status.ble.{event}",
                    name=str(payload.get("name", "")).strip(),
                    address=addr(),
                    old_name=str(payload.get("old_name", "")).strip(),
                )
                + remainder
            )
        if event == "already_connected":
            return t("status.ble.already_connected", address=addr()) + remainder
        if event == "connecting":
            return t("status.ble.connecting", address=addr()) + remainder
        if event == "disconnected":
            return t("status.ble.disconnected") + remainder
        if event == "static_color_mode":
            return t("status.static_color_mode") + remainder
        if event == "brightness_set":
            return t("status.ble.brightness_set", value=val()) + remainder
        if event == "brightness_restore":
            return t("status.ble.brightness_restore", value=val()) + remainder
        if event == "effect_speed_set":
            return t("status.ble.effect_speed_set", value=val()) + remainder
        if event == "effect_applied":
            return t("status.ble.effect_applied", code=str(payload.get("code", "")).strip()) + remainder
        if event == "driver_selected":
            return t("status.ble.driver_selected", driver=str(payload.get("driver", "")).strip()) + remainder
        if event == "candidate_characteristics":
            return t("status.ble.candidate_characteristics", uuids=str(payload.get("uuids", "")).strip()) + remainder
        if event == "reconnect_success":
            return t("status.ble.reconnect_success", address=addr()) + remainder
        if event == "reconnect_give_up":
            return t("status.ble.reconnect_give_up", address=addr()) + remainder
        if event == "power":
            key = "status.ble.power_on" if bool(payload.get("enabled", False)) else "status.ble.power_off"
            return t(key) + remainder
        if event in {"color_set", "color_restore"}:
            key = f"status.ble.{event}"
            return t(key, red=int(payload.get("red", 0)), green=int(payload.get("green", 0)), blue=int(payload.get("blue", 0))) + remainder
        if event == "connected_via":
            return t("status.ble.connected_via", name=str(payload.get("name", "")).strip(), uuid=str(payload.get("uuid", "")).strip()) + remainder
        if event == "unexpected_disconnect":
            return t("status.ble.unexpected_disconnect", name=str(payload.get("name", "")).strip(), address=addr()) + remainder
        if event in {"reconnect_attempt", "reconnect_failed_attempt"}:
            kwargs: dict = {
                "address": addr(),
                "attempt": int(payload.get("attempt", 0)),
                "total": int(payload.get("total", 0)),
            }
            if event == "reconnect_failed_attempt":
                kwargs["error"] = str(payload.get("error", "")).strip()
            return t(f"status.ble.{event}", **kwargs) + remainder
        if event == "write_retry":
            return t("status.ble.write_retry", uuid=str(payload.get("uuid", "")).strip(),
                     attempt=int(payload.get("attempt", 0)), total=int(payload.get("total", 0)),
                     error=str(payload.get("error", "")).strip()) + remainder
        if event == "write_failed":
            return t("status.ble.write_failed", error=str(payload.get("error", "")).strip()) + remainder
        return None

    def _normalize_legacy(self, message: str) -> str:
        for key in ("status.ready_find", "status.static_color_mode", "status.defaults_restored", "status.profile_loaded_local"):
            if message in self.translation_variants(key):
                return self.t(key)

        if message.startswith("Config '") and message.endswith("' saved."):
            return self.normalize_status_message(self.status_config_event("saved",   name=message.removeprefix("Config '").removesuffix("' saved.")))
        if message.startswith("Config '") and message.endswith("' loaded."):
            return self.normalize_status_message(self.status_config_event("loaded",  name=message.removeprefix("Config '").removesuffix("' loaded.")))
        if message.startswith("Config '") and message.endswith("' deleted."):
            return self.normalize_status_message(self.status_config_event("deleted", name=message.removeprefix("Config '").removesuffix("' deleted.")))

        if ru_m := re.fullmatch(r"Конфиг «(.+?)» (сохранён|загружен|удалён)\.", message):
            raw_name, action_text = ru_m.groups()
            return self.normalize_status_message(self.status_config_event({"сохранён": "saved", "загружен": "loaded", "удалён": "deleted"}[action_text], name=raw_name))

        if zh_m := re.fullmatch('配置“(.+?)”已(保存|加载|删除)。', message):
            raw_name, action_text = zh_m.groups()
            return self.normalize_status_message(self.status_config_event({"保存": "saved", "加载": "loaded", "删除": "deleted"}[action_text], name=raw_name))

        for prefix in ("BLE error: ", "BLE 错误：", "Ошибка BLE: "):
            if message.startswith(prefix):
                return self._format_ble_error(message[len(prefix):])

        return message


localization_manager = LocalizationManager()

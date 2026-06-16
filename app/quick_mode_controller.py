from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.localization import localization_manager
from app.quick_modes import QUICK_MODE_MAP
from app.storage import DEFAULT_START_COLOR


@dataclass
class ProfileState:
    name: str
    power: bool
    brightness: int
    speed: int
    effect_code: int
    schedule: dict
    color: dict


class QuickModeController:
    def __init__(self, host) -> None:
        self._host = host

    def refresh_buttons(self) -> None:
        host = self._host
        for key, button in host._mode_buttons.items():
            button.setText(host._tr(f"mode.{key}"))
            mode = QUICK_MODE_MAP.get(key)
            is_supported = True if mode is None else self.effect_code(mode) is not None
            button.setEnabled(is_supported or key == host._active_mode_key)
            button.set_role("mode_active" if key == host._active_mode_key else "mode")
        for index, button in enumerate(host._custom_mode_buttons):
            if index >= len(host._custom_quick_modes):
                button.hide()
                continue
            mode = host._custom_quick_modes[index]
            key = str(mode.get("key", ""))
            name = self.custom_name(mode, index)
            button.setText(name[:18])
            button.setToolTip(name)
            button.setEnabled(self.effect_code(mode) is not None or key == host._active_mode_key)
            button.set_role("mode_active" if key == host._active_mode_key else "mode")
            button.set_embedded_action("x", lambda slot=index: self.finish_delete_custom(slot))
            button.show()
        host.save_quick_mode_button.setToolTip(host._tr("mode.save_current"))

    def set_active(self, mode_key: str | None, *, update_theme: bool = True) -> None:
        host = self._host
        normalized = mode_key if mode_key in self.keys() else None
        if normalized == host._active_mode_key:
            return
        host._active_mode_key = normalized
        host._settings["quick_mode"] = normalized or ""
        self.refresh_buttons()
        if update_theme:
            host._theme_controller.apply_theme()

    def current_state(self) -> dict:
        host = self._host
        color = host._current_color()
        return {
            "power": host.power_button.isChecked(),
            "brightness": host.brightness_slider.value(),
            "speed": host.speed_slider.value(),
            "effect_code": int(host.effect_combo.currentData() or 0),
            "color": {"r": color.red(), "g": color.green(), "b": color.blue()},
        }

    def sync_from_state(self, preferred: str | None = None) -> None:
        host = self._host
        if host._initializing:
            return
        state = self.current_state()
        preferred_mode = self.by_key(preferred or "")
        if preferred_mode is not None and self.matches(preferred_mode, state):
            self.set_active(self.mode_key(preferred_mode))
            return
        active_mode = self.by_key(host._active_mode_key or "")
        if active_mode is not None and not self.matches(active_mode, state):
            self.set_active(None, update_theme=False)

    def activate(self, mode_key: str) -> None:
        host = self._host
        mode = self.by_key(mode_key)
        if mode is None:
            return
        effect_code = self.effect_code(mode)
        if host._is_connected and effect_code is None:
            host._show_error(host._tr("error.effects_not_supported"))
            return
        self.set_active(self.mode_key(mode))
        payload = self.payload(mode)
        if effect_code is not None:
            payload["effect_code"] = effect_code
        color = payload.get("color", {})
        host._aurora.set_accent_color(
            int(color.get("r", 0)),
            int(color.get("g", 0)),
            int(color.get("b", 0)),
            enabled=bool(payload.get("power", True)),
        )
        host._profile_actions.apply_profile_payload(payload, announce_load=False)

    def activate_custom(self, index: int) -> None:
        host = self._host
        if index < 0 or index >= len(host._custom_quick_modes):
            return
        self.activate(str(host._custom_quick_modes[index].get("key", "")))

    def rename_custom(self, index: int) -> None:
        self.activate_custom(index)

    def finish_rename_custom(self, index: int, name: str) -> None:
        if name.strip():
            self._host._log(self._host._tr("mode.rename_in_configs"))

    def delete_custom(self, index: int) -> None:
        self.finish_delete_custom(index)

    def finish_delete_custom(self, index: int) -> None:
        host = self._host
        if index < 0 or index >= len(host._custom_quick_modes):
            return
        mode = host._custom_quick_modes.pop(index)
        key = str(mode.get("key", ""))
        name = self.custom_name(mode, index)
        if host._active_mode_key == key:
            host._active_mode_key = None
            host._settings["quick_mode"] = ""
        host._settings["custom_quick_modes"] = host._custom_quick_modes
        host._persist_settings()
        self.refresh_buttons()
        host._log(host._tr("mode.unpinned_log", name=name))

    def save_custom(self) -> None:
        host = self._host
        if not host._can_use("custom_quick_modes"):
            host._show_license_overlay()
            return
        if len(host._custom_quick_modes) >= 4:
            host._show_error(host._tr("error.custom_quick_limit"))
            return
        profile = host._profile_controller.selected_profile(host.profile_list)
        if profile is None:
            host._show_error(host._tr("error.select_profile_first"))
            return
        self.pin_profile(profile)

    def finish_save_custom(self, name: str) -> None:
        profile = self._find_profile_by_name(name.strip())
        if profile is not None:
            self.pin_profile(profile)
            return
        host = self._host
        clean_name = name.strip()
        if not clean_name:
            host._show_error(host._tr("error.enter_profile_name"))
            return
        payload = host._state_to_dict(self.collect_state(clean_name))
        payload["key"] = self.next_custom_key()
        color = payload.get("color", {})
        payload["accent"] = f"#{int(color.get('r', 0)):02x}{int(color.get('g', 0)):02x}{int(color.get('b', 0)):02x}"
        host._custom_quick_modes.append(payload)
        host._settings["custom_quick_modes"] = host._custom_quick_modes
        host._settings["quick_mode"] = payload["key"]
        host._persist_settings()
        self.set_active(payload["key"])
        host._log(host._tr("mode.saved_log", name=clean_name))

    def pin_profile(self, profile: dict) -> None:
        host = self._host
        profile_name = str(profile.get("name", "")).strip()
        if not profile_name:
            host._show_error(host._tr("error.select_profile_first"))
            return
        if self._is_profile_pinned(profile_name):
            host._show_error(host._tr("mode.already_pinned", name=localization_manager.profile_name(profile)))
            return
        payload = dict(profile)
        payload["key"] = self.next_custom_key()
        payload["source_profile_name"] = profile_name
        color = payload.get("color", {})
        payload["accent"] = f"#{int(color.get('r', 0)):02x}{int(color.get('g', 0)):02x}{int(color.get('b', 0)):02x}"
        host._custom_quick_modes.append(payload)
        host._settings["custom_quick_modes"] = host._custom_quick_modes
        host._settings["quick_mode"] = payload["key"]
        host._persist_settings()
        self.set_active(payload["key"])
        host._log(host._tr("mode.pinned_log", name=localization_manager.profile_name(profile)))

    def collect_state(self, name: str) -> ProfileState:
        host = self._host
        color = host._current_color()
        return ProfileState(
            name=name,
            power=host.power_button.isChecked(),
            brightness=host.brightness_slider.value(),
            speed=host.speed_slider.value(),
            effect_code=int(host.effect_combo.currentData() or 0),
            schedule=host._schedule_ctrl.settings(),
            color={"r": color.red(), "g": color.green(), "b": color.blue()},
        )

    def next_custom_key(self) -> str:
        existing = {str(mode.get("key", "")) for mode in self._host._custom_quick_modes}
        index = 1
        while f"custom_{index}" in existing:
            index += 1
        return f"custom_{index}"

    def custom_name(self, mode: dict, index: int) -> str:
        current_profile = self._profile_for_pinned_mode(mode)
        if current_profile is not None:
            return localization_manager.profile_name(current_profile)
        name = str(mode.get("name", "")).strip()
        if not name or name == "Desk Scene":
            return self._host._tr("mode.custom_default", number=index + 1)
        return localization_manager.profile_name(mode)

    def keys(self) -> set[str]:
        host = self._host
        return {*QUICK_MODE_MAP.keys(), *(str(mode.get("key", "")) for mode in host._custom_quick_modes)}

    def by_key(self, mode_key: str) -> Any:
        built_in = QUICK_MODE_MAP.get(mode_key)
        if built_in is not None:
            return built_in
        for mode in self._host._custom_quick_modes:
            if str(mode.get("key", "")) == mode_key:
                return mode
        return None

    def mode_key(self, mode) -> str:
        return mode.key if hasattr(mode, "key") else str(mode.get("key", ""))

    def payload(self, mode) -> dict:
        host = self._host
        if hasattr(mode, "as_profile"):
            return mode.as_profile()
        pinned_profile = self._profile_for_pinned_mode(mode)
        if pinned_profile is not None:
            return dict(pinned_profile)
        return {
            "name": str(mode.get("name", "")),
            "power": bool(mode.get("power", True)),
            "brightness": int(mode.get("brightness", 100)),
            "speed": int(mode.get("speed", 60)),
            "effect_code": int(mode.get("effect_code", 0)),
            "color": dict(mode.get("color", DEFAULT_START_COLOR)),
            "schedule": dict(mode.get("schedule", host._schedule_ctrl.settings())),
        }

    def effect_code(self, mode) -> int | None:
        host = self._host
        effect_code = int(mode.effect_code if hasattr(mode, "effect_code") else mode.get("effect_code", 0))
        mode_key = self.mode_key(mode)
        if effect_code == 0 or host._ble.supports_effect_code(effect_code):
            return effect_code
        if mode_key != "rainbow":
            return None
        for effect in host._ble.effect_presets():
            if effect.key in {"smooth_rainbow", "smooth_spectrum", "triones_rainbow", "magic_home_rainbow"}:
                if host._ble.supports_effect_code(effect.code):
                    return effect.code
        return None

    def matches(self, mode, state: dict) -> bool:
        if hasattr(mode, "matches") and mode.matches(state):
            return True
        if not hasattr(mode, "matches"):
            return self._custom_mode_matches(mode, state)
        effect_code = self.effect_code(mode)
        original_effect_code = int(mode.effect_code if hasattr(mode, "effect_code") else mode.get("effect_code", 0))
        if effect_code is None or effect_code == original_effect_code:
            return False
        return (
            bool(state.get("power")) == bool(mode.power if hasattr(mode, "power") else mode.get("power", True))
            and int(state.get("brightness", -1)) == int(mode.brightness if hasattr(mode, "brightness") else mode.get("brightness", 100))
            and int(state.get("effect_code", -1)) == effect_code
            and int(state.get("speed", -1)) == int(mode.speed if hasattr(mode, "speed") else mode.get("speed", 60))
        )

    def _custom_mode_matches(self, mode: dict, state: dict) -> bool:
        mode = self.payload(mode)
        mode_effect_code = int(mode.get("effect_code", 0))
        if bool(state.get("power")) != bool(mode.get("power", True)):
            return False
        if int(state.get("brightness", -1)) != int(mode.get("brightness", 100)):
            return False
        if int(state.get("effect_code", -1)) != mode_effect_code:
            return False
        if mode_effect_code != 0:
            return int(state.get("speed", -1)) == int(mode.get("speed", 60))
        color = mode.get("color", {})
        state_color = state.get("color", {})
        return (
            int(state_color.get("r", -1)),
            int(state_color.get("g", -1)),
            int(state_color.get("b", -1)),
        ) == (
            int(color.get("r", -2)),
            int(color.get("g", -2)),
            int(color.get("b", -2)),
        )

    def _find_profile_by_name(self, name: str) -> dict | None:
        normalized = name.strip().lower()
        if not normalized:
            return None
        for profile in self._host._profiles:
            if str(profile.get("name", "")).strip().lower() == normalized:
                return profile
        return None

    def _profile_for_pinned_mode(self, mode: dict) -> dict | None:
        source_name = str(mode.get("source_profile_name", "")).strip()
        return self._find_profile_by_name(source_name)

    def _is_profile_pinned(self, profile_name: str) -> bool:
        normalized = profile_name.strip().lower()
        for mode in self._host._custom_quick_modes:
            source = str(mode.get("source_profile_name") or mode.get("name", "")).strip().lower()
            if source == normalized:
                return True
        return False

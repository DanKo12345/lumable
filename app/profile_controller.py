from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from app.app_info import APP_NAME, APP_VERSION
from app.feature_gate import ProfileLimitError, ensure_profile_capacity
from app.localization import localization_manager
from app.storage import reset_profiles, save_profiles, validate_profiles_payload


class ProfileController:
    def __init__(self, profiles: list[dict]) -> None:
        self._profiles = profiles

    @property
    def profiles(self) -> list[dict]:
        return self._profiles

    def refresh_list(self, profile_list: QListWidget) -> None:
        profile_list.clear()
        for index, profile in enumerate(self._profiles, start=1):
            display_name = localization_manager.profile_name(profile)
            item = QListWidgetItem(f"{index}. {display_name}")
            item.setData(Qt.UserRole, profile)
            profile_list.addItem(item)

    def selected_profile(self, profile_list: QListWidget) -> dict | None:
        item = profile_list.currentItem()
        return None if item is None else item.data(Qt.UserRole)

    def user_profile_count(self) -> int:
        return sum(1 for profile in self._profiles if not str(profile.get("preset_key", "")).strip())

    def save_profile(
        self,
        name: str,
        collect_state: Callable[[str], object],
        on_error: Callable[[str], None],
        on_log: Callable[[str], None],
        translate: Callable[[str], str],
        profile_list: QListWidget,
    ) -> None:
        clean_name = name.strip()
        if not clean_name:
            on_error(translate("error.enter_profile_name"))
            return
        state = asdict(collect_state(clean_name))
        for index, profile in enumerate(self._profiles):
            if str(profile.get("name", "")).lower() == clean_name.lower():
                self._profiles[index] = state
                break
        else:
            try:
                ensure_profile_capacity(self.user_profile_count())
            except ProfileLimitError:
                on_error(translate("error.profile_limit_free"))
                return
            self._profiles.append(state)
        save_profiles(self._profiles)
        self.refresh_list(profile_list)
        on_log(localization_manager.status_config_event("saved", name=clean_name))

    def delete_selected_profile(
        self,
        profile_list: QListWidget,
        on_error: Callable[[str], None],
        on_log: Callable[[str], None],
        translate: Callable[[str], str],
    ) -> None:
        profile = self.selected_profile(profile_list)
        if profile is None:
            on_error(translate("error.select_profile_first"))
            return
        selected_name = str(profile.get("name", ""))
        self._profiles[:] = [entry for entry in self._profiles if str(entry.get("name", "")) != selected_name]
        save_profiles(self._profiles)
        self.refresh_list(profile_list)
        on_log(localization_manager.status_config_event("deleted", profile))

    def rename_selected_profile(
        self,
        profile_list: QListWidget,
        new_name: str,
        on_error: Callable[[str], None],
        on_log: Callable[[str], None],
        translate: Callable[[str], str],
    ) -> None:
        profile = self.selected_profile(profile_list)
        clean_name = new_name.strip()
        if profile is None:
            on_error(translate("error.select_profile_first"))
            return
        if not clean_name:
            on_error(translate("error.enter_profile_name"))
            return
        old_name = str(profile.get("name", ""))
        for entry in self._profiles:
            if entry is not profile and str(entry.get("name", "")).strip().lower() == clean_name.lower():
                on_error(translate("error.profile_name_exists"))
                return
        profile["name"] = clean_name
        save_profiles(self._profiles)
        self.refresh_list(profile_list)
        on_log(translate("status.profile_renamed", old=old_name, new=clean_name))

    def reset_profiles(
        self,
        profile_list: QListWidget,
        on_log: Callable[[str], None],
        translate: Callable[[str], str],
    ) -> None:
        self._profiles[:] = reset_profiles()
        self.refresh_list(profile_list)
        on_log(translate("status.defaults_restored"))

    def export_profiles(self, path: Path) -> int:
        payload = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "profiles": self._profiles,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(self._profiles)

    def import_profiles(self, path: Path, *, replace: bool = False) -> tuple[int, int]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        imported_profiles, skipped = validate_profiles_payload(payload)
        if not imported_profiles:
            return 0, skipped

        if replace:
            self._profiles[:] = imported_profiles
        else:
            by_name = {str(profile.get("name", "")).strip().lower(): index for index, profile in enumerate(self._profiles)}
            for profile in imported_profiles:
                name = str(profile.get("name", "")).strip().lower()
                if name and name in by_name:
                    self._profiles[by_name[name]] = profile
                else:
                    self._profiles.append(profile)
                    if name:
                        by_name[name] = len(self._profiles) - 1
        save_profiles(self._profiles)
        return len(imported_profiles), skipped

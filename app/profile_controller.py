from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from app.localization import localization_manager
from app.storage import reset_profiles, save_profiles


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
            item.setIcon(self._profile_icon(profile))
            profile_list.addItem(item)

    def selected_profile(self, profile_list: QListWidget) -> dict | None:
        item = profile_list.currentItem()
        return None if item is None else item.data(Qt.UserRole)

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
            if profile["name"].lower() == clean_name.lower():
                self._profiles[index] = state
                break
        else:
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
        self._profiles[:] = [entry for entry in self._profiles if entry["name"] != profile["name"]]
        save_profiles(self._profiles)
        self.refresh_list(profile_list)
        on_log(localization_manager.status_config_event("deleted", profile))

    def reset_profiles(
        self,
        profile_list: QListWidget,
        on_log: Callable[[str], None],
        translate: Callable[[str], str],
    ) -> None:
        self._profiles[:] = reset_profiles()
        self.refresh_list(profile_list)
        on_log(translate("status.defaults_restored"))

    @staticmethod
    def _profile_icon(profile: dict) -> QIcon:
        color_data = profile.get("color", {})
        color = QColor(
            int(color_data.get("r", 132)),
            int(color_data.get("g", 168)),
            int(color_data.get("b", 236)),
        )
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(1, 1, 12, 12)
        painter.end()
        return QIcon(pixmap)

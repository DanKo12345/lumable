from __future__ import annotations

from json import JSONDecodeError
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog

from app.ble import BleController
from app.feature_gate import can_use
from app.localization import localization_manager
from app.profile_controller import ProfileController
from app.schedule_controller import ScheduleController
from app.widgets import ProfileConfirmOverlay, ProfileRenameOverlay


class ProfileActionsHost(Protocol):
    _ble: BleController
    _effect_debounce: Any
    _is_connected: bool
    _profile_controller: ProfileController
    _schedule_ctrl: ScheduleController

    profile_name: Any
    profile_list: Any
    red_slider: Any
    green_slider: Any
    blue_slider: Any
    brightness_slider: Any
    speed_slider: Any
    effect_combo: Any
    power_button: Any
    preview: Any

    def _tr(self, key: str, **kwargs: object) -> str: ...

    def _collect_state(self, name: str) -> object: ...

    def _current_color(self) -> QColor: ...

    def _show_error(self, message: str) -> None: ...

    def _show_license_overlay(self) -> None: ...

    def _log(self, message: str) -> None: ...

    def _refresh_profiles(self) -> None: ...

    def _sync_power_button(self) -> None: ...

    def _sync_aurora_accent(self, *, enabled: bool | None = None) -> None: ...

    def _sync_effect_preview(self, *, reset_phase: bool = False) -> None: ...

    def _sync_quick_mode_from_state(self, preferred: str | None = None) -> None: ...

    def _update_preview(self) -> None: ...

    def _remember_current_color(self) -> None: ...

    def _suppress_signals(self): ...


class ProfileActions:
    def __init__(self, host: ProfileActionsHost) -> None:
        self._host = host

    def save_profile(self) -> None:
        host = self._host
        host._profile_controller.save_profile(
            host.profile_name.text(),
            host._collect_state,
            host._show_error,
            host._log,
            host._tr,
            host.profile_list,
        )

    def selected_profile(self) -> dict | None:
        return self._host._profile_controller.selected_profile(self._host.profile_list)

    def load_selected_profile(self) -> None:
        host = self._host
        profile = self.selected_profile()
        if profile is None:
            host._show_error(host._tr("error.select_profile_first"))
            return
        self.apply_profile_payload(profile, announce_load=True)

    def delete_selected_profile(self) -> None:
        host = self._host
        profile = self.selected_profile()
        if profile is None:
            host._show_error(host._tr("error.select_profile_first"))
            return
        labels = {
            "title": host._tr("configs.delete_confirm_title"),
            "message": host._tr("configs.delete_confirm_text", name=localization_manager.profile_name(profile)),
            "cancel": host._tr("dialog.cancel"),
            "delete": host._tr("configs.delete_confirm"),
        }
        if not ProfileConfirmOverlay(labels, host).exec():
            return
        host._profile_controller.delete_selected_profile(
            host.profile_list,
            host._show_error,
            host._log,
            host._tr,
        )

    def rename_selected_profile(self) -> None:
        host = self._host
        profile = self.selected_profile()
        if profile is None:
            host._show_error(host._tr("error.select_profile_first"))
            return
        current_name = localization_manager.profile_name(profile)
        labels = {
            "title": host._tr("configs.rename_title"),
            "prompt": host._tr("configs.rename_prompt"),
            "cancel": host._tr("dialog.cancel"),
            "ok": host._tr("dialog.ok"),
        }
        new_name = ProfileRenameOverlay(labels, current_name, host).exec()
        if new_name is None:
            return
        host._profile_controller.rename_selected_profile(
            host.profile_list,
            new_name,
            host._show_error,
            host._log,
            host._tr,
        )

    def reset_profiles(self) -> None:
        host = self._host
        host._profile_controller.reset_profiles(
            host.profile_list,
            host._log,
            host._tr,
        )

    def export_profiles(self) -> None:
        host = self._host
        if not can_use("profile_export"):
            host._show_license_overlay()
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            None,
            host._tr("configs.export_title"),
            str(Path.home() / "Desktop" / "lumable-profiles.json"),
            host._tr("configs.file_filter"),
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            count = host._profile_controller.export_profiles(Path(path))
        except OSError as exc:
            host._show_error(host._tr("configs.export_error", error=str(exc)))
            return
        host._log(host._tr("configs.exported", count=count, path=Path(path).name))

    def import_profiles(self) -> None:
        host = self._host
        if not can_use("profile_import"):
            host._show_license_overlay()
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            None,
            host._tr("configs.import_title"),
            str(Path.home() / "Desktop"),
            host._tr("configs.file_filter"),
        )
        if not path:
            return
        try:
            count, skipped = host._profile_controller.import_profiles(Path(path), replace=False)
        except (OSError, JSONDecodeError) as exc:
            host._show_error(host._tr("configs.import_error", error=str(exc)))
            return
        if count <= 0:
            host._show_error(host._tr("configs.import_empty"))
            return
        host._refresh_profiles()
        host._log(host._tr("configs.imported", count=count, skipped=skipped))

    def apply_profile_payload(self, profile: dict, *, announce_load: bool = False) -> None:
        host = self._host
        host._effect_debounce.stop()
        previous_power = host.power_button.isChecked()
        with host._suppress_signals():
            color = profile["color"]
            host.red_slider.setValue(int(color["r"]))
            host.green_slider.setValue(int(color["g"]))
            host.blue_slider.setValue(int(color["b"]))
            host.brightness_slider.setValue(int(profile["brightness"]))
            host.speed_slider.setValue(int(profile["speed"]))
            idx = host.effect_combo.findData(int(profile["effect_code"]))
            host.effect_combo.setCurrentIndex(idx if idx >= 0 else 0)
            host.power_button.setChecked(bool(profile["power"]))
            host._sync_power_button()
            host._update_preview()
            host.preview.set_brightness(host.brightness_slider.value())
            host._sync_effect_preview(reset_phase=True)
            if "schedule" in profile:
                host._schedule_ctrl.apply_settings(profile.get("schedule", {}), save=True, run_check=True)
        if announce_load:
            host._log(localization_manager.status_config_event("loaded", profile))
        host._sync_aurora_accent()
        host._sync_quick_mode_from_state()
        if not host._is_connected:
            if announce_load:
                host._log(host._tr("status.profile_loaded_local"))
                host._show_error(host._tr("error.connect_strip_to_apply_profile"))
            else:
                host._show_error(host._tr("error.connect_strip_first"))
            return
        target_power = host.power_button.isChecked()
        if previous_power != target_power:
            host._ble.set_power(target_power, restore_state=False)
        if not target_power:
            host._sync_aurora_accent(enabled=False)
            return
        effect_code = int(host.effect_combo.currentData() or 0)
        if effect_code == 0:
            color_obj = host._current_color()
            host._ble.set_static_color(
                color_obj.red(),
                color_obj.green(),
                color_obj.blue(),
                host.brightness_slider.value(),
            )
            host._remember_current_color()
        else:
            host._ble.set_effect_with_speed(effect_code, host.speed_slider.value())

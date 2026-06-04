from __future__ import annotations

from app.feature_gate import is_pro
from app.localization import localization_manager
from app.storage import save_settings


class UiLocalizationController:
    def __init__(self, host) -> None:
        self._host = host

    def apply_texts(self) -> None:
        host = self._host
        host.hero_title.setText(host._tr("hero.title"))
        host.hero_subtitle.setText(host._tr("hero.subtitle"))
        host.hero_signature.refresh_text()
        host.hero_signature.set_edition(
            host._tr("app.edition.pro") if is_pro() else host._tr("app.edition.free"),
            host._tr("app.edition.tooltip"),
        )
        host.about_button.setToolTip(host._tr("tray.about"))
        self.refresh_language_options()
        host._refresh_quick_mode_buttons()

        self._apply_device_texts()
        self._apply_color_texts()
        self._apply_effect_texts()
        self._apply_config_texts()
        self._apply_schedule_texts()
        self._apply_diagnostics_texts()

        host._refresh_diagnostics_view()
        host._refresh_effect_names()
        host._refresh_profiles()
        host._tray_controller.sync_texts()

    def refresh_language_options(self) -> None:
        host = self._host
        current_language = host._language
        host.language_combo.blockSignals(True)
        host.language_combo.clear()
        for language in localization_manager.available_languages():
            host.language_combo.addItem(localization_manager.language_name(language), language)
        host.language_combo.addItem(host._tr("language.reload"), host.RELOAD_LANGUAGES_ACTION)
        index = host.language_combo.findData(current_language)
        host.language_combo.setCurrentIndex(index if index >= 0 else 0)
        host.language_combo.blockSignals(False)

    def reload_languages(self) -> None:
        host = self._host
        snapshot = host.grab()
        localization_manager.reload()
        if host._language not in localization_manager.available_languages():
            host._language = localization_manager.language
            host._settings["language"] = host._language
            save_settings(host._settings)
        self.apply_texts()
        self.refresh_localized_log_lines()
        host._theme_controller.sync_theme_button()
        host.preview.refresh_text()
        host._log(host._tr("status.languages_reloaded"))
        host._theme_controller.animate_overlay_fade(snapshot, duration=210)

    def refresh_localized_log_lines(self) -> None:
        self._host._ui_feedback.refresh_logs()

    def _apply_device_texts(self) -> None:
        host = self._host
        host.device_card.title_label.setText(host._tr("device.title"))
        if host.device_card.subtitle_label is not None:
            host.device_card.subtitle_label.setText(host._tr("device.subtitle"))
        host.scan_button.setText(host._tr("device.find"))
        host.connect_button.setText(host._tr("device.connect"))
        host.disconnect_button.setText(host._tr("device.disconnect"))
        host.device_status.setText(
            host._tr("device.status.connected") if host._is_connected else host._tr("device.status.not_connected")
        )
        host._ble_events._sync_last_device_hint(autoconnecting=host._connect_in_progress)
        host.logs_toggle_button.setText(host._tr("device.show_logs"))
        host._sync_connect_buttons()

    def _apply_color_texts(self) -> None:
        host = self._host
        host.color_card.title_label.setText(host._tr("color.title"))
        if host.color_card.subtitle_label is not None:
            host.color_card.subtitle_label.setText(host._tr("color.subtitle"))
        host.pick_color_button.setText(host._tr("color.pick"))
        host.color_history_label.setText(host._tr("color.recent"))
        host._sync_power_button()
        host._set_slider_label_text("slider.red", host._tr("slider.red"))
        host._set_slider_label_text("slider.green", host._tr("slider.green"))
        host._set_slider_label_text("slider.blue", host._tr("slider.blue"))
        host._set_slider_label_text("slider.brightness", host._tr("slider.brightness"))

    def _apply_effect_texts(self) -> None:
        host = self._host
        host.effects_card.title_label.setText(host._tr("effects.title"))
        if host.effects_card.subtitle_label is not None:
            host.effects_card.subtitle_label.setText(host._tr("effects.subtitle"))
        host._set_slider_label_text("effects.speed", host._tr("effects.speed"))

    def _apply_config_texts(self) -> None:
        host = self._host
        host.configs_card.title_label.setText(host._tr("configs.title"))
        if host.configs_card.subtitle_label is not None:
            host.configs_card.subtitle_label.setText(host._tr("configs.subtitle"))
        host.profile_name.setPlaceholderText(host._tr("configs.placeholder"))
        host.save_profile_button.setText(host._tr("configs.save"))
        host.import_profiles_button.setToolTip(host._tr("configs.import_tooltip"))
        host.export_profiles_button.setToolTip(host._tr("configs.export_tooltip"))
        host.configs_menu_button.setToolTip(host._tr("configs.menu"))
        host.reset_profiles_action.setText(host._tr("configs.menu_reset"))

    def _apply_schedule_texts(self) -> None:
        host = self._host
        host.schedule_card.title_label.setText(host._tr("schedule.title"))
        if host.schedule_card.subtitle_label is not None:
            host.schedule_card.subtitle_label.setText(host._tr("schedule.subtitle"))
        host.schedule_runtime_note.setText(host._tr("schedule.runtime_note"))
        host.schedule_on_label.setText(host._tr("schedule.on"))
        host.schedule_off_label.setText(host._tr("schedule.off"))
        host.schedule_on_time.set_picker_title(host._tr("schedule.pick_on"))
        host.schedule_off_time.set_picker_title(host._tr("schedule.pick_off"))
        time_picker_labels = {
            "hours": host._tr("time_picker.hours"),
            "minutes": host._tr("time_picker.minutes"),
            "ok": host._tr("dialog.ok"),
        }
        host.schedule_on_time.set_picker_labels(**time_picker_labels)
        host.schedule_off_time.set_picker_labels(**time_picker_labels)
        host._schedule_ctrl.sync_controls()

    def _apply_diagnostics_texts(self) -> None:
        host = self._host
        host.diagnostics_card.title_label.setText(host._tr("diagnostics.title"))
        if host.diagnostics_card.subtitle_label is not None:
            host.diagnostics_card.subtitle_label.setText(host._tr("diagnostics.subtitle"))
        host.copy_diagnostics_button.setText(host._tr("diagnostics.copy"))
        host.show_logs_button.setText(host._tr("device.show_logs"))
        host.export_diagnostics_button.setText(host._tr("diagnostics.export"))
        host.check_update_button.setText(
            host._tr("updates.open")
            if host._update_result is not None and host._update_result.state == "available"
            else host._tr("updates.check")
        )

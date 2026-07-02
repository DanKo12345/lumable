from __future__ import annotations

from app.feature_gate import is_pro
from app.localization import localization_manager
from app.panels.diagnostics_panel import resize_diagnostics_action_buttons
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
        host.about_button.setText(host._tr("settings.about"))
        host.about_button.setToolTip(host._tr("tray.about"))
        for nav_key, nav_button in getattr(host, "_nav_buttons", {}).items():
            nav_button.setText(host._tr(f"nav.{nav_key}"))
        for label_key, label in getattr(host, "_settings_labels", []):
            label.setText(host._tr(label_key))
        self.refresh_language_options()
        self._apply_performance_texts()
        host._refresh_quick_mode_buttons()

        self._apply_device_texts()
        self._apply_color_texts()
        self._apply_effect_texts()
        self._apply_config_texts()
        self._apply_schedule_texts()
        self._apply_ambient_texts()
        self._apply_music_texts()
        self._apply_software_fx_texts()
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
        host.device_onboarding_label.setText(host._tr("device.onboarding_hint"))
        host.connect_button.setText(host._tr("device.connect"))
        host.disconnect_button.setText(host._tr("device.disconnect"))
        add_mirror = getattr(host, "add_mirror_button", None)
        if add_mirror is not None:
            add_mirror.setText(host._tr("device.add_mirror"))
        host.device_status.setText(
            host._tr("device.status.connected") if host._is_connected else host._tr("device.status.not_connected")
        )
        hint = getattr(host, "device_status_hint", None)
        if hint is not None:
            if host._is_connected:
                name = str(host._settings.get("last_device_name") or host._settings.get("last_device_address") or "")
                hint.setText(name)
                hint.setVisible(bool(name))
            else:
                hint.setText(host._tr("device.connect_hint"))
                hint.setVisible(True)
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
        host._set_slider_label_text("slider.temperature", host._tr("slider.temperature"))

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
        host.schedule_toggle_button.setToolTip(host._tr("schedule.toggle_hint"))
        host.schedule_startup_button.setToolTip(host._tr("schedule.startup_hint"))
        host.schedule_on_label.setText(host._tr("schedule.on"))
        host.schedule_off_label.setText(host._tr("schedule.off"))
        for index, chip in enumerate(getattr(host, "schedule_day_buttons", [])):
            chip.setText(host._tr(f"schedule.day_{index}"))
        if getattr(host, "schedule_lock_label", None) is not None:
            host.schedule_lock_label.setText(host._tr("schedule.pro_locked"))
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
        if getattr(host, "app_triggers_card", None) is not None:
            host.app_triggers_card.title_label.setText(host._tr("app_triggers.title"))
            if host.app_triggers_card.subtitle_label is not None:
                host.app_triggers_card.subtitle_label.setText(host._tr("app_triggers.subtitle"))
            host.app_triggers_default_label.setText(host._tr("app_triggers.default_label"))
            host.app_triggers_add_button.setText(host._tr("app_triggers.add_rule"))
            host._app_trigger_ui.relocalize()
        if getattr(host, "hotkeys_card", None) is not None:
            host.hotkeys_card.title_label.setText(host._tr("hotkeys.title"))
            if host.hotkeys_card.subtitle_label is not None:
                host.hotkeys_card.subtitle_label.setText(host._tr("hotkeys.subtitle"))
            host.hotkeys_lock_label.setText(host._tr("hotkeys.pro_locked"))
            host._hotkey_ui.relocalize()

    def _apply_performance_texts(self) -> None:
        host = self._host
        combo = host.performance_combo
        current = host._settings.get("ui_fps", "auto") if isinstance(host._settings, dict) else "auto"
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(host._tr("performance.auto"), "auto")
        for rate in ("30", "60", "120"):
            combo.addItem(f"{rate} FPS", rate)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        combo.setToolTip(host._tr("performance.tooltip"))

    def _apply_ambient_texts(self) -> None:
        host = self._host
        host.ambient_card.title_label.setText(host._tr("ambient.title"))
        if host.ambient_card.subtitle_label is not None:
            host.ambient_card.subtitle_label.setText(host._tr("ambient.subtitle"))
        host._set_slider_label_text("ambient.saturation", host._tr("ambient.saturation"))
        host._set_slider_label_text("ambient.smoothing", host._tr("ambient.smoothing"))
        running = host._ambient_ui.is_running()
        host.ambient_toggle_button.setText(host._tr("ambient.toggle_on" if running else "ambient.toggle_off"))
        if getattr(host, "ambient_lock_label", None) is not None:
            host.ambient_lock_label.setText(host._tr("ambient.pro_locked"))
        host._ambient_ui.refresh_lock()

        combo = host.ambient_region_combo
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for region in ("full", "center", "bottom", "top"):
            combo.addItem(host._tr(f"ambient.region.{region}"), region)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

        if host.ambient_monitor_combo is not None:
            from PySide6.QtGui import QGuiApplication

            monitor_combo = host.ambient_monitor_combo
            selected = monitor_combo.currentData()
            monitor_combo.blockSignals(True)
            monitor_combo.clear()
            for screen_index, screen in enumerate(QGuiApplication.screens()):
                geometry = screen.geometry()
                monitor_combo.addItem(
                    f"{host._tr('ambient.monitor')} {screen_index + 1} ({geometry.width()}×{geometry.height()})",
                    screen_index,
                )
            monitor_index = monitor_combo.findData(selected)
            monitor_combo.setCurrentIndex(monitor_index if monitor_index >= 0 else 0)
            monitor_combo.blockSignals(False)

    def _apply_music_texts(self) -> None:
        host = self._host
        host.music_card.title_label.setText(host._tr("music.title"))
        if host.music_card.subtitle_label is not None:
            host.music_card.subtitle_label.setText(host._tr("music.subtitle"))
        host._set_slider_label_text("music.speed", host._tr("music.speed"))
        host._set_slider_label_text("music.beat", host._tr("music.beat"))
        host._set_slider_label_text("music.gate", host._tr("music.gate"))
        source_segment = getattr(host, "music_source_segment", None)
        is_mic = getattr(host._music_ui, "_source", "system") == "mic"
        if source_segment is not None:
            source_segment.set_labels({
                "system": host._tr("music.source_system"),
                "mic": host._tr("music.source_mic"),
            })
        source_combo = getattr(host, "music_source_combo", None)
        if source_combo is not None and source_combo.count() > 0:
            source_combo.setItemText(0, host._tr("music.source_default_mic" if is_mic else "music.source_default"))
            source_combo.setToolTip(host._tr("music.source_hint"))
        host._set_slider_label_text("music.saturation", host._tr("music.saturation"))
        host._set_slider_label_text("music.smoothing", host._tr("music.smoothing"))
        running = host._music_ui.is_running()
        host.music_toggle_button.setText(host._tr("music.toggle_on" if running else "music.toggle_off"))
        if getattr(host, "music_lock_label", None) is not None:
            host.music_lock_label.setText(host._tr("music.pro_locked"))
        if running and getattr(host, "music_status_label", None) is not None:
            host.music_status_label.setText(host._tr("music.listening"))
        captions = getattr(host, "music_band_captions", {})
        for band, label_key in (("bass", "music.band_bass"), ("mid", "music.band_mid"), ("treble", "music.band_treble")):
            caption = captions.get(band)
            if caption is not None:
                caption.setText(host._tr(label_key))
        host._music_ui.refresh_lock()

    def _apply_software_fx_texts(self) -> None:
        from app.software_effects import EFFECT_KEYS

        host = self._host
        host.software_fx_card.title_label.setText(host._tr("software_fx.title"))
        if host.software_fx_card.subtitle_label is not None:
            host.software_fx_card.subtitle_label.setText(host._tr("software_fx.subtitle"))
        host._set_slider_label_text("software_fx.speed", host._tr("software_fx.speed"))
        running = host._software_fx_ui.is_running()
        host.software_fx_toggle.setText(host._tr("software_fx.toggle_on" if running else "software_fx.toggle_off"))
        combo = host.software_fx_combo
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for key in EFFECT_KEYS:
            combo.addItem(host._tr(f"software_fx.effect_{key}"), key)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        if getattr(host, "diy_card", None) is not None:
            host.diy_card.title_label.setText(host._tr("diy.title"))
            if host.diy_card.subtitle_label is not None:
                host.diy_card.subtitle_label.setText(host._tr("diy.subtitle"))
            host.diy_lock_label.setText(host._tr("diy.pro_locked"))
            host._diy_ui.relocalize()

    def _apply_diagnostics_texts(self) -> None:
        host = self._host
        host.diagnostics_card.title_label.setText(host._tr("diagnostics.title"))
        if host.diagnostics_card.subtitle_label is not None:
            host.diagnostics_card.subtitle_label.setText(host._tr("diagnostics.subtitle"))
        host.diagnostics_support_label.setText(host._tr("diagnostics.support_hint"))
        host.copy_diagnostics_button.setText(host._tr("diagnostics.copy"))
        host.copy_diagnostics_button.setToolTip(host._tr("diagnostics.support_hint"))
        host.show_logs_button.setText(host._tr("device.show_logs"))
        host.export_diagnostics_button.setText(host._tr("diagnostics.export"))
        host.export_diagnostics_button.setToolTip(host._tr("diagnostics.support_hint"))
        host.check_update_button.setText(
            host._tr("updates.open")
            if host._update_result is not None and host._update_result.state == "available"
            else host._tr("updates.check")
        )
        resize_diagnostics_action_buttons(host)

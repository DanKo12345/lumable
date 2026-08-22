from __future__ import annotations

from app.capture_regions import REGION_IDS
from app.feature_gate import is_pro
from app.localization import localization_manager
from app.motion_policy import DEFAULT_MOTION_MODE, normalize_motion_mode
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
        for label_key, label, control in getattr(host, "_settings_labels", []):
            text = host._tr(label_key)
            label.setText(text)
            control.setAccessibleName(text)  # keep assistive tools on the new language
        self.refresh_language_options()
        self._apply_performance_texts()
        self._apply_motion_texts()
        host._refresh_quick_mode_buttons()

        self._apply_device_texts()
        self._apply_color_texts()
        self._apply_scenes_texts()
        self._apply_effect_texts()
        self._apply_config_texts()
        self._apply_schedule_texts()
        self._apply_automations_texts()
        self._apply_ambient_texts()
        self._apply_music_texts()
        self._apply_software_fx_texts()
        self._apply_diagnostics_texts()
        self._apply_local_api_texts()

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
        for attribute, key in (
            ("device_primary_heading", "device.primary_section"),
            ("device_mirrors_heading", "device.mirrors_section"),
            ("mirror_empty_label", "device.mirrors_empty"),
            ("rename_device_button", "device.rename_primary"),
            ("supported_controllers_button", "device.supported"),
        ):
            widget = getattr(host, attribute, None)
            if widget is not None:
                widget.setText(host._tr(key))
        host.device_status.setText(
            host._tr("device.status.connected") if host._is_connected else host._tr("device.status.not_connected")
        )
        primary_meta = getattr(host, "device_primary_meta", None)
        if primary_meta is not None and not host._is_connected:
            primary_meta.setText(host._tr("device.primary_empty"))
        hint = getattr(host, "device_status_hint", None)
        if hint is not None:
            if host._is_connected:
                name = str(host._settings.get("last_device_name") or host._settings.get("last_device_address") or "")
                hint.setText(name)
                wanted = bool(name)
            else:
                hint.setText(host._tr("device.connect_hint"))
                wanted = True
            apply_hint = getattr(host, "_set_status_hint_visible", None)
            if callable(apply_hint):
                apply_hint(wanted)  # compact sidebar may override on a short window
            else:
                hint.setVisible(wanted)
        host._ble_events._sync_last_device_hint(autoconnecting=host._connect_in_progress)
        host.logs_toggle_button.setText(host._tr("device.show_logs"))
        host.supported_controllers_button.setText(host._tr("device.supported"))
        host.rename_device_button.setText(host._tr("device.rename"))
        host._sync_connect_buttons()

    def _apply_color_texts(self) -> None:
        host = self._host
        host.color_card.title_label.setText(host._tr("color.title"))
        if host.color_card.subtitle_label is not None:
            host.color_card.subtitle_label.setText(host._tr("color.subtitle"))
        host.pick_color_button.setText(host._tr("color.pick"))
        host.color_history_label.setText(host._tr("color.recent"))
        host.color_channels_label.setText(host._tr("color.channels"))
        host.color_light_label.setText(host._tr("color.light"))
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
        host.configs_library_label.setText(host._tr("configs.library_title"))
        host.configs_library_hint.setText(host._tr("configs.library_hint"))
        host.configs_saved_label.setText(host._tr("configs.saved_title"))
        host.configs_saved_hint.setText(host._tr("configs.saved_hint"))
        host.profile_name.setPlaceholderText(host._tr("configs.placeholder"))
        host.save_profile_button.setText(host._tr("configs.save"))
        for button, key in (
            (host.import_profiles_button, "configs.import_tooltip"),
            (host.export_profiles_button, "configs.export_tooltip"),
            (host.configs_menu_button, "configs.menu"),
        ):
            label = host._tr(key)
            button.setToolTip(label)
            button.setAccessibleName(label)
        host.reset_profiles_action.setText(host._tr("configs.menu_reset"))

    def _apply_schedule_texts(self) -> None:
        host = self._host
        host.schedule_card.title_label.setText(host._tr("schedule.title"))
        if host.schedule_card.subtitle_label is not None:
            host.schedule_card.subtitle_label.setText(host._tr("schedule.subtitle"))
        host.schedule_runtime_note.setText(host._tr("schedule.runtime_note"))
        host.schedule_toggle_button.setToolTip(host._tr("schedule.toggle_hint"))
        host.schedule_startup_button.setToolTip(host._tr("schedule.startup_hint"))
        host.schedule_master_label.setText(host._tr("schedule.row_master"))
        host.schedule_on_label.setText(host._tr("schedule.row_on"))
        host.schedule_off_label.setText(host._tr("schedule.row_off"))
        host.schedule_days_label.setText(host._tr("schedule.row_days"))
        host.schedule_startup_label.setText(host._tr("schedule.row_startup"))
        host.schedule_startup_status.setText(host._tr("schedule.startup_hint"))
        for index, chip in enumerate(getattr(host, "schedule_day_buttons", [])):
            chip.setText(host._tr(f"schedule.day_{index}"))
        if getattr(host, "schedule_lock_label", None) is not None:
            host.schedule_lock_label.setText(host._tr("common.pro_badge"))
            host.schedule_lock_label.setToolTip(host._tr("schedule.pro_locked"))
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
        if getattr(host, "timers_card", None) is not None:
            host.timers_card.title_label.setText(host._tr("timers.title"))
            if host.timers_card.subtitle_label is not None:
                host.timers_card.subtitle_label.setText(host._tr("timers.subtitle"))
            host.timer_sleep_label.setText(host._tr("timers.sleep"))
            host.timer_sleep_after.setText(host._tr("timers.sleep_after"))
            # The pills paint only a number, so their accessible name carries the
            # purpose — it has to follow the language like the visible labels do.
            host.timer_sleep_pill.set_purpose(host._tr("timers.sleep_after"))
            host.timer_sunrise_pill.set_purpose(host._tr("timers.sunrise"))
            host.timer_sunrise_label.setText(host._tr("timers.sunrise"))
            host.timer_sunrise_at.setText(host._tr("timers.sunrise_at"))
            host.timer_sunrise_time.set_picker_title(host._tr("timers.sunrise"))
            host.timer_sunrise_time.set_picker_labels(
                hours=host._tr("time_picker.hours"),
                minutes=host._tr("time_picker.minutes"),
                ok=host._tr("dialog.ok"),
            )
            host._timer_ctrl.relocalize()
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
            host._hotkey_ui.relocalize()

    def _apply_automations_texts(self) -> None:
        host = self._host
        if getattr(host, "automations_card", None) is None:
            return
        host.automations_card.title_label.setText(host._tr("automations.title"))
        if host.automations_card.subtitle_label is not None:
            host.automations_card.subtitle_label.setText(host._tr("automations.subtitle"))
        host.automations_master_label.setText(host._tr("automations.row_master"))
        host.automations_pause_label.setText(host._tr("automations.row_pause"))
        host.automations_rules_card.title_label.setText(host._tr("automations.rules_title"))
        if host.automations_rules_card.subtitle_label is not None:
            host.automations_rules_card.subtitle_label.setText(host._tr("automations.rules_subtitle"))
        host.automations_empty_hint.setText(host._tr("automations.empty_hint"))
        host.automations_add_button.setText(host._tr("automations.add_rule"))
        host.automations_journal_card.title_label.setText(host._tr("automations.journal_title"))
        if host.automations_journal_card.subtitle_label is not None:
            host.automations_journal_card.subtitle_label.setText(host._tr("automations.journal_subtitle"))
        host.automations_journal_empty.setText(host._tr("automations.journal_empty"))
        host.automations_bridge_card.title_label.setText(host._tr("automations.bridge_title"))
        # Every row's text is generated from its rule, and the pause row's from the
        # pause state, so the controller regenerates them rather than being patched.
        host._automation_ui.relocalize()

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

    def _apply_motion_texts(self) -> None:
        host = self._host
        combo = getattr(host, "motion_combo", None)
        if combo is None:
            return
        current = (
            normalize_motion_mode(host._settings.get("motion_mode", DEFAULT_MOTION_MODE))
            if isinstance(host._settings, dict)
            else DEFAULT_MOTION_MODE
        )
        # Stable itemData (system/reduced/full) — never compared by localized text.
        # Block signals so relabelling on a language change never re-saves the mode.
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(host._tr("motion.system"), "system")
        combo.addItem(host._tr("motion.reduced"), "reduced")
        combo.addItem(host._tr("motion.full"), "full")
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        combo.setToolTip(host._tr("motion.tooltip"))

    def _apply_ambient_texts(self) -> None:
        host = self._host
        host.ambient_card.title_label.setText(host._tr("ambient.title"))
        if host.ambient_card.subtitle_label is not None:
            host.ambient_card.subtitle_label.setText(host._tr("ambient.subtitle"))
        host._set_slider_label_text("ambient.intensity", host._tr("ambient.intensity"))
        host._set_slider_label_text("ambient.smoothness", host._tr("ambient.smoothness"))
        if getattr(host, "ambient_preview_label", None) is not None:
            host.ambient_preview_label.setText(host._tr("ambient.preview_hint"))
        if getattr(host, "ambient_profile_segment", None) is not None:
            host.ambient_profile_segment.set_labels(
                {pid: host._tr(f"ambient.profile.{pid}") for pid in ("desktop", "game", "movie")}
            )
        if getattr(host, "fusion_mode_segment", None) is not None:
            host.fusion_mode_segment.set_labels(
                {key: host._tr(f"fusion.mode.{key}") for key in ("screen", "screen_music")}
            )
        if getattr(host, "fusion_source_segment", None) is not None:
            host.fusion_source_segment.set_labels(
                {"system": host._tr("music.source_system"), "mic": host._tr("music.source_mic")}
            )
            host.fusion_source_segment.setAccessibleName(host._tr("music.source_title"))
        if getattr(host, "fusion_beat_label", None) is not None:
            host.fusion_beat_label.setText(host._tr("music.beat"))
            host.fusion_beat_slider.setAccessibleName(host._tr("music.beat"))
        if getattr(host, "fusion_tune_button", None) is not None:
            host.fusion_tune_button.setAccessibleName(host._tr("fusion.tune"))
            host.fusion_tune_button.setToolTip(host._tr("fusion.tune"))
        host._ambient_ui.refresh_texts()
        host.ambient_toggle_button.setText(host._tr(host._fusion_ui.toggle_label_key()))
        if getattr(host, "ambient_lock_label", None) is not None:
            host.ambient_lock_label.setText(host._tr("common.pro_badge"))
            host.ambient_lock_label.setToolTip(host._tr("ambient.pro_locked"))
        host._ambient_ui.refresh_lock()

        host.ambient_area_selector.set_texts(
            title=host._tr("ambient.area_title"),
            help_text=host._tr("ambient.area_help"),
            labels={region: host._tr(f"ambient.region.{region}") for region in REGION_IDS},
            tooltips={region: host._tr(f"ambient.region_tip.{region}") for region in REGION_IDS},
        )

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
        host.music_mode_label.setText(host._tr("music.mode_title"))
        host.music_source_label.setText(host._tr("music.source_title"))
        host.music_reaction_label.setText(host._tr("music.reaction_title"))
        host.music_colors_label.setText(host._tr("music.colors_title"))
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
            host.music_lock_label.setText(host._tr("common.pro_badge"))
            host.music_lock_label.setToolTip(host._tr("music.pro_locked"))
        if getattr(host, "music_status_label", None) is not None:
            host.music_status_label.setText(
                host._tr("music.listening" if running else "music.status_off")
            )
        host.music_source_description.setText(
            host._tr("music.source_mic_desc" if is_mic else "music.source_system_desc")
        )
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
            host.diy_lock_label.setText(host._tr("common.pro_badge"))
            host.diy_lock_label.setToolTip(host._tr("diy.pro_locked"))
            host._diy_ui.relocalize()

    def _apply_scenes_texts(self) -> None:
        host = self._host
        if getattr(host, "scenes_card", None) is None:
            return
        host.scenes_card.title_label.setText(host._tr("scenes.title"))
        if host.scenes_card.subtitle_label is not None:
            host.scenes_card.subtitle_label.setText(host._tr("scenes.subtitle"))
        if getattr(host, "groups_card", None) is not None:
            host.groups_card.title_label.setText(host._tr("groups.title"))
            if host.groups_card.subtitle_label is not None:
                host.groups_card.subtitle_label.setText(host._tr("groups.subtitle"))
        host._scene_ui.relocalize()

    def _apply_local_api_texts(self) -> None:
        host = self._host
        host.api_card.title_label.setText(host._tr("api.title"))
        if host.api_card.subtitle_label is not None:
            host.api_card.subtitle_label.setText(host._tr("api.subtitle"))
        host.api_token_label.setText(host._tr("api.token"))
        host.api_port_label.setText(host._tr("api.port"))
        host.api_copy_token_button.setText(host._tr("api.copy_token"))
        host.api_regenerate_button.setText(host._tr("api.regenerate"))
        host.api_lan_button.setText(host._tr("api.allow_lan"))
        host.api_lan_host_field.setPlaceholderText(host._tr("api.lan_host_placeholder"))
        host.api_lan_warning.setText(host._tr("api.lan_warning"))
        host.api_security_note.setText(host._tr("api.security_note"))
        host.api_help_button.setText(host._tr("api.help"))
        host.api_pair_button.setText(host._tr("api.pair"))
        advanced_open = host.api_advanced_toggle.isChecked()
        host.api_advanced_toggle.setText(host._tr("api.advanced_hide" if advanced_open else "api.advanced"))
        host._local_api.relocalize()

    def _apply_diagnostics_texts(self) -> None:
        host = self._host
        host.diagnostics_card.title_label.setText(host._tr("diagnostics.title"))
        if host.diagnostics_card.subtitle_label is not None:
            host.diagnostics_card.subtitle_label.setText(host._tr("diagnostics.subtitle"))
        host.diagnostics_support_label.setText(host._tr("diagnostics.support_hint"))
        host.diagnostics_report_label.setText(host._tr("diagnostics.report_section"))
        host.diagnostics_logs_label.setText(host._tr("diagnostics.logs_title"))
        host.diagnostics_logs_hint.setText(host._tr("diagnostics.logs_hint"))
        host.diagnostics_scan_label.setText(host._tr("diagnostics.scan_title"))
        host.diagnostics_scan_hint.setText(host._tr("diagnostics.scan_hint"))
        host.diagnostics_update_label.setText(host._tr("diagnostics.updates_title"))
        host.diagnostics_update_hint.setText(host._tr("diagnostics.updates_hint"))
        host.copy_diagnostics_button.setAccessibleName(host._tr("diagnostics.copy"))
        host.copy_diagnostics_button.setToolTip(
            f"{host._tr('diagnostics.copy')}\n{host._tr('diagnostics.support_hint')}"
        )
        host.report_device_button.setText(host._tr("diagnostics.report"))
        host.report_device_button.setToolTip(host._tr("diagnostics.report_hint"))
        host.show_logs_button.setText(host._tr("diagnostics.open"))
        host.export_diagnostics_button.setAccessibleName(host._tr("diagnostics.export"))
        host.export_diagnostics_button.setToolTip(
            f"{host._tr('diagnostics.export')}\n{host._tr('diagnostics.support_hint')}"
        )
        host.export_scan_button.setText(host._tr("diagnostics.save"))
        host.export_scan_button.setToolTip(host._tr("scan_snapshot.export_hint"))
        host.check_update_button.setText(
            host._tr("updates.open")
            if host._update_result is not None and host._update_result.state == "available"
            else host._tr("updates.check")
        )
        resize_diagnostics_action_buttons(host)

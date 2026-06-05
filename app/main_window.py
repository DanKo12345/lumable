from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QTextEdit,
)

from app.app_info import APP_ORGANIZATION, APP_RELEASES_URL, APP_UPDATE_URL, APP_VERSION
from app.ble import BleController
from app.ble_event_handler import BleEventHandler
from app.constants import (
    CHIP_HEIGHT,
    CONTROL_HEIGHT,
    SLIDER_LABEL_WIDTH,
    SLIDER_ROW_MARGINS,
    SLIDER_ROW_SPACING,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from app.diagnostics import build_diagnostics_report
from app.feature_gate import can_use, free_effect_limit
from app.localization import localization_manager
from app.main_layout import build_main_layout
from app.overlay_controller import OverlayController
from app.profile_actions import ProfileActions
from app.profile_controller import ProfileController
from app.quick_modes import QUICK_MODE_MAP
from app.schedule_controller import ScheduleController
from app.shortcut_controller import ShortcutController
from app.storage import DEFAULT_START_COLOR, load_profiles, load_settings, save_settings
from app.theme import theme_manager
from app.theme_controller import ThemeController
from app.tray_controller import TrayController
from app.ui_feedback import UiFeedback
from app.ui_localization_controller import UiLocalizationController
from app.update_checker import UpdateResult
from app.update_controller import UpdateController
from app.widgets import (
    AuroraBackground,
    ColorPickerOverlay,
    GlassCard,
    LiquidButton,
    LiquidSlider,
    LogsOverlay,
    SmoothScrollFilter,
    ValueChip,
)
from app.window_state_controller import WindowStateController


@dataclass
class ProfileState:
    name: str
    power: bool
    brightness: int
    speed: int
    effect_code: int
    schedule: dict
    color: dict


class MainWindow(QMainWindow):
    RELOAD_LANGUAGES_ACTION = "__reload_i18n__"

    def __init__(self):
        super().__init__()
        QCoreApplication.setOrganizationName(APP_ORGANIZATION)
        QCoreApplication.setApplicationVersion(APP_VERSION)
        self.setWindowTitle(localization_manager.t("dialog.title"))
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self._init_state()
        self._init_controllers()
        self._init_timers()
        self._build_ui()
        self._theme_controller.apply_theme()
        self._wire_events()
        self._load_initial_state()
        self._tray_controller.setup()
        self._apply_windows_backdrop()
        self._schedule_ctrl.start()
        QTimer.singleShot(500, self._ble_events.start_autoconnect)
        QTimer.singleShot(1600, self._update_controller.check_silent)

    def _init_state(self) -> None:
        """Initialise plain data attributes before any controller is created."""
        self._control_height = CONTROL_HEIGHT
        self._chip_height = CHIP_HEIGHT
        self._settings = load_settings()
        self._theme_mode = self._settings.get("theme_mode") or self._settings.get("theme", "dark")
        self._language = self._settings.get("language", "ru")
        localization_manager.set_language(self._language)
        if self._theme_mode not in {"dark", "light", "auto"}:
            self._theme_mode = "auto"
        self._is_dark = ThemeController.resolve_dark_from_mode(self._theme_mode)
        self._theme_tokens = theme_manager.set_dark(self._is_dark)
        self._profiles = load_profiles()
        self._devices: list = []
        self._is_connected = False
        self._initializing = False
        self._close_after_ble_shutdown = False
        self._close_requested = False
        self._force_quit_requested = False
        self._scan_in_progress = False
        self._connect_in_progress = False
        self._connect_button_phase = 0
        self._active_mode_key: str | None = None
        self._theme_transition = None
        self._theme_transition_overlay = None
        self._update_result: UpdateResult | None = None
        # Widget refs set later by _build_ui / build_main_layout
        self.content_shell = None
        self.diagnostics_output = None
        self._ui_feedback = None
        self._buttons: list[LiquidButton] = []
        self._slider_labels: dict[str, QLabel] = {}
        self._scroll_filters: list = []

    def _init_controllers(self) -> None:
        """Create all controller objects that wrap MainWindow logic."""
        self._profile_controller = ProfileController(self._profiles)
        self._profile_actions = ProfileActions(self)
        self._ble = BleController()
        self._ble_events = BleEventHandler(self)
        self._update_controller = UpdateController(self, APP_VERSION, APP_UPDATE_URL, APP_RELEASES_URL)
        self._update_checker = self._update_controller.checker
        self._shortcut_controller = ShortcutController(self)
        self._shortcuts = self._shortcut_controller.shortcuts
        self._overlay_controller = OverlayController(self)
        self._theme_controller = ThemeController(self)
        self._tray_controller = TrayController(self)
        self._ui_localization = UiLocalizationController(self)
        self._schedule_ctrl = ScheduleController(self)
        self._window_state = WindowStateController(self)
        self._aurora = AuroraBackground(self)
        self._aurora.lower()

    def _init_timers(self) -> None:
        """Create and configure all QTimer instances."""
        self._auto_theme_timer = QTimer(self)
        self._auto_theme_timer.setInterval(60_000)
        self._auto_theme_timer.timeout.connect(self._theme_controller.refresh_auto_theme)
        self._auto_theme_timer.start()

        self._effect_debounce = QTimer(self)
        self._effect_debounce.setSingleShot(True)
        self._effect_debounce.setInterval(180)
        self._effect_debounce.timeout.connect(self._apply_selected_effect)

        self._color_apply_debounce = QTimer(self)
        self._color_apply_debounce.setSingleShot(True)
        self._color_apply_debounce.setInterval(120)
        self._color_apply_debounce.timeout.connect(self._apply_current_color)

        self._connect_button_timer = QTimer(self)
        self._connect_button_timer.setInterval(450)
        self._connect_button_timer.timeout.connect(self._tick_connect_button_animation)

    def _tr(self, key: str, **kwargs) -> str:
        return localization_manager.t(key, **kwargs)

    @contextmanager
    def _suppress_signals(self):
        previous = self._initializing
        self._initializing = True
        try:
            yield
        finally:
            self._initializing = previous

    def _build_ui(self):
        root = build_main_layout(self)
        self._apply_localized_texts()
        self._install_smooth_scroll(self.profile_list, step=46, duration=105)
        self._install_smooth_scroll(self.diagnostics_output, step=54, duration=185)
        self._install_smooth_scroll(self.body_scroll, step=72, duration=210)
        self.log_output = QTextEdit(self)
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.hide()
        self._ui_feedback = UiFeedback(self, self.log_output, lambda: self._theme_tokens, self._tr)
        self.setCentralWidget(root)
        self._window_state.sync_content_shell_width()

    def _sync_content_shell_width(self):
        self._window_state.sync_content_shell_width()

    def _apply_localized_texts(self):
        self._ui_localization.apply_texts()

    def _show_about_overlay(self) -> None:
        self._overlay_controller.show_about()

    def _show_license_overlay(self) -> None:
        self._overlay_controller.show_license()

    def _refresh_effect_names(self):
        current_code = self.effect_combo.currentData()
        effects = list(self._ble.effect_presets())
        unlocked_count = len(effects) if can_use("all_effects") else free_effect_limit()
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        self._effect_key_by_code = {effect.code: effect.key for effect in effects[:unlocked_count]}
        for index, effect in enumerate(effects):
            name = localization_manager.effect_name(effect.key)
            if index < unlocked_count:
                self.effect_combo.addItem(name, effect.code)
            else:
                self.effect_combo.addItem(f"🔒 {name}", None)
        idx = self.effect_combo.findData(current_code)
        self.effect_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.effect_combo.blockSignals(False)
        self._sync_speed_controls()

    def _refresh_language_options(self):
        self._ui_localization.refresh_language_options()

    def _reload_languages(self):
        self._ui_localization.reload_languages()

    def _refresh_localized_log_lines(self):
        self._ui_localization.refresh_localized_log_lines()

    def _set_slider_label_text(self, key: str, text: str):
        label = self._slider_labels.get(key)
        if label is not None:
            label.setText(text)

    def _card(self, title: str, subtitle: str | None = None, icon: str | None = None) -> GlassCard:
        return GlassCard(title, subtitle, icon=icon)

    def _button(self, text: str, role: str) -> LiquidButton:
        button = LiquidButton(text, role)
        font = button.font()
        font.setPointSize(11)
        font.setWeight(QFont.DemiBold)
        button.setFont(font)
        self._buttons.append(button)
        return button

    def _slider(self, accent: str) -> LiquidSlider:
        return LiquidSlider(accent)

    def _pill(self, text: str) -> ValueChip:
        label = ValueChip(text)
        label.setMinimumWidth(68)
        label.setMinimumHeight(CHIP_HEIGHT)
        return label

    def _slider_row(self, name: str, slider: LiquidSlider, value: ValueChip, key: str | None = None):
        layout = QHBoxLayout()
        layout.setSpacing(SLIDER_ROW_SPACING)
        layout.setContentsMargins(*SLIDER_ROW_MARGINS)
        label = QLabel(name)
        label.setObjectName("sliderLabel")
        label.setFixedWidth(SLIDER_LABEL_WIDTH)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if key is not None:
            self._slider_labels[key] = label
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value, 0)
        return layout

    def _install_smooth_scroll(self, widget, step: int = 58, duration: int = 180):
        viewport = widget.viewport() if hasattr(widget, "viewport") else widget
        scroll_filter = SmoothScrollFilter(widget, step=step, duration=duration)
        viewport.installEventFilter(scroll_filter)
        self._scroll_filters.append(scroll_filter)

    def _wire_events(self):
        self._wire_device_events()
        self._wire_theme_events()
        self._wire_color_events()
        self._wire_profile_events()
        self._wire_ble_events()
        self._wire_update_events()
        self._wire_diagnostics_events()
        self._wire_schedule_events()
        self._wire_shortcuts()

    def _wire_device_events(self):
        self.scan_button.clicked.connect(self._ble_events.start_scan)
        self.connect_button.clicked.connect(self._ble_events.handle_connect)
        self.disconnect_button.clicked.connect(self._ble.disconnect)
        self.logs_toggle_button.clicked.connect(self._show_logs_overlay)

    def _wire_shortcuts(self):
        self._shortcut_controller.wire()

    def _shortcuts_accept_action(self) -> bool:
        return self._shortcut_controller.accepts_action()

    def _handle_power_shortcut(self) -> None:
        self._shortcut_controller.handle_power()

    def _handle_quick_mode_shortcut(self, mode_key: str) -> None:
        self._shortcut_controller.handle_quick_mode(mode_key)

    def _wire_theme_events(self):
        self.theme_button.clicked.connect(self._theme_controller.toggle_theme)
        self.language_combo.currentIndexChanged.connect(self._change_language)

    def _wire_color_events(self):
        self.pick_color_button.clicked.connect(self._pick_color)
        self.power_button.clicked.connect(self._toggle_power)
        self.effect_combo.currentIndexChanged.connect(self._queue_selected_effect)
        self.speed_slider.valueChanged.connect(lambda v: self.speed_value.setText(f"{v}%"))
        self.speed_slider.valueChanged.connect(self.effect_preview.set_speed)
        self.speed_slider.sliderReleased.connect(self._apply_speed)
        self.speed_value.activated.connect(lambda: self._edit_slider_value(self.speed_slider, self.speed_value, suffix="%"))
        for index, button in enumerate(self.color_history_buttons):
            button.clicked.connect(lambda _checked=False, swatch_index=index: self._apply_color_history_item(swatch_index))
        self._wire_rgb_slider_events()
        self.brightness_slider.valueChanged.connect(lambda v: self.brightness_value.setText(f"{v}%"))
        self.brightness_slider.valueChanged.connect(self.preview.set_brightness)
        self.brightness_slider.valueChanged.connect(self._queue_current_color_update)
        self.brightness_value.activated.connect(
            lambda: self._edit_slider_value(self.brightness_slider, self.brightness_value, suffix="%")
        )

    def _wire_rgb_slider_events(self):
        for slider, label in (
            (self.red_slider, self.red_value),
            (self.green_slider, self.green_value),
            (self.blue_slider, self.blue_value),
        ):
            slider.valueChanged.connect(lambda v, t=label: t.setText(str(v)))
            label.activated.connect(lambda s=slider, value_chip=label: self._edit_slider_value(s, value_chip))
            slider.valueChanged.connect(self._update_preview)
            slider.valueChanged.connect(self._queue_current_color_update)

    def _edit_slider_value(self, slider: LiquidSlider, value_label: ValueChip, *, suffix: str = ""):
        value, ok = QInputDialog.getInt(
            self,
            self._tr("dialog.slider_value_title"),
            self._tr("dialog.slider_value_label"),
            slider.value(),
            slider.minimum(),
            slider.maximum(),
        )
        if not ok:
            return
        slider.setValue(value)
        value_label.setText(f"{value}{suffix}")
        if slider in {self.red_slider, self.green_slider, self.blue_slider}:
            self._update_preview()

    def _wire_profile_events(self):
        self.save_profile_button.clicked.connect(self._profile_actions.save_profile)
        self.profile_list.itemClicked.connect(lambda _item: self._profile_actions.load_selected_profile())
        self.profile_list.renameRequested.connect(self._profile_actions.rename_selected_profile)
        self.profile_list.deleteRequested.connect(self._profile_actions.delete_selected_profile)
        self.reset_profiles_action.triggered.connect(self._profile_actions.reset_profiles)
        self.import_profiles_button.clicked.connect(self._profile_actions.import_profiles)
        self.export_profiles_button.clicked.connect(self._profile_actions.export_profiles)

    def _wire_ble_events(self):
        self._ble.status_changed.connect(self._log)
        self._ble.devices_discovered.connect(self._ble_events.populate_devices)
        self._ble.connected_changed.connect(self._ble_events.on_connected_changed)
        self._ble.error_occurred.connect(self._show_error)
        self._ble.shutdown_finished.connect(self._finish_close_after_ble_shutdown)

    def _wire_update_events(self):
        self._update_controller.wire()

    def _wire_diagnostics_events(self):
        self.copy_diagnostics_button.clicked.connect(self._copy_diagnostics_report)
        self.export_diagnostics_button.clicked.connect(self._export_diagnostics_report)
        self.show_logs_button.clicked.connect(self._show_logs_overlay)

    def _wire_schedule_events(self):
        self._schedule_ctrl.wire()

    def _toggle_schedule(self, _checked: bool = False) -> None:
        self._schedule_ctrl.toggle_schedule(_checked)

    def _sync_schedule_controls(self) -> None:
        self._schedule_ctrl.sync_controls()

    def _check_schedule(self) -> None:
        self._schedule_ctrl._check_schedule()

    def _load_initial_state(self):
        self._restore_startup_size()
        last = self._settings.get("last_state", {})
        color = last.get("color", DEFAULT_START_COLOR)
        with self._suppress_signals():
            self.red_slider.setValue(int(color.get("r", DEFAULT_START_COLOR["r"])))
            self.green_slider.setValue(int(color.get("g", DEFAULT_START_COLOR["g"])))
            self.blue_slider.setValue(int(color.get("b", DEFAULT_START_COLOR["b"])))
            self.brightness_slider.setValue(int(last.get("brightness", 100)))
            self.speed_slider.setValue(int(last.get("speed", 60)))
            # BLEDOM-style controllers do not expose a reliable readback for the
            # active built-in effect, so startup must not present a stale saved mode.
            idx = self.effect_combo.findData(0)
            self.effect_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.power_button.setChecked(bool(last.get("power", True)))
            self._sync_power_button()
            self._refresh_profiles()
            self._update_preview()
            self.preview.set_brightness(self.brightness_slider.value())
            self._sync_effect_preview()
            self._refresh_color_history()
            self._schedule_ctrl.load_state()
            self._sync_connect_buttons()
            self._log(self._tr("status.ready_find"))
        self._sync_aurora_accent()
        self._sync_quick_mode_from_state(preferred=self._settings.get("quick_mode"))

    def _restore_startup_size(self):
        self._window_state.restore_startup_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_content_shell_width()
        self._aurora.setGeometry(0, 0, self.width(), self.height())

    def _apply_windows_backdrop(self):
        self._window_state.apply_windows_backdrop()

    def _current_color(self):
        return QColor(self.red_slider.value(), self.green_slider.value(), self.blue_slider.value())

    def _update_preview(self):
        self.preview.set_color(self._current_color())

    def _sync_aurora_accent(self, *, enabled: bool | None = None) -> None:
        color = self._current_color()
        active = self.power_button.isChecked() if enabled is None else bool(enabled)
        self._aurora.set_accent_color(color.red(), color.green(), color.blue(), enabled=active)

    def _color_history(self) -> list[dict[str, int]]:
        history = self._settings.get("color_history", [])
        return history if isinstance(history, list) else []

    def _refresh_color_history(self) -> None:
        visible_limit = 12 if can_use("color_history_full") else 3
        history = self._color_history()[:visible_limit]
        for index, button in enumerate(self.color_history_buttons):
            if index >= len(history):
                button.hide()
                continue
            item = history[index]
            button.set_color(QColor(int(item.get("r", 0)), int(item.get("g", 0)), int(item.get("b", 0))))
            button.show()

    def _remember_current_color(self) -> None:
        color = self._current_color()
        rgb = {"r": color.red(), "g": color.green(), "b": color.blue()}
        history = [
            item
            for item in self._color_history()
            if not (
                int(item.get("r", -1)) == rgb["r"]
                and int(item.get("g", -1)) == rgb["g"]
                and int(item.get("b", -1)) == rgb["b"]
            )
        ]
        limit = 12 if can_use("color_history_full") else 3
        self._settings["color_history"] = [rgb, *history][:limit]
        save_settings(self._settings)
        self._refresh_color_history()

    def _apply_color_history_item(self, index: int) -> None:
        history = self._color_history()
        if index < 0 or index >= len(history):
            return
        item = history[index]
        with self._suppress_signals():
            self.red_slider.setValue(int(item.get("r", 0)))
            self.green_slider.setValue(int(item.get("g", 0)))
            self.blue_slider.setValue(int(item.get("b", 0)))
            self._update_preview()
        self._apply_current_color()

    def _sync_effect_preview(self, *, reset_phase: bool = False):
        data = self.effect_combo.currentData()
        code = int(data or 0)
        self._sync_speed_controls()
        self.effect_preview.set_effect(self._effect_key_by_code.get(code, "static_color"), code, reset_phase=reset_phase)
        self.effect_preview.set_speed(self.speed_slider.value())

    def _sync_speed_controls(self):
        is_static = int(self.effect_combo.currentData() or 0) == 0
        supports_speed = self._ble.supports_effect_speed()
        visible = not is_static
        enabled = visible and supports_speed
        speed_label = self._slider_labels.get("effects.speed")
        if speed_label is not None:
            speed_label.setVisible(visible)
        self.speed_slider.setVisible(visible)
        self.speed_slider.setEnabled(enabled)
        self.speed_value.setVisible(visible)
        self.speed_value.setEnabled(enabled)

    def _pick_color(self):
        if not can_use("color_picker_hsv"):
            self._show_license_overlay()
            return
        picker = ColorPickerOverlay(
            self._tr("dialog.pick_color"),
            self._current_color(),
            {
                "red": self._tr("slider.red"),
                "green": self._tr("slider.green"),
                "blue": self._tr("slider.blue"),
                "hex": self._tr("color.hex"),
                "recent": self._tr("color.recent"),
                "cancel": self._tr("dialog.cancel"),
                "ok": self._tr("dialog.ok"),
            },
            self._color_history(),
            self,
        )
        if not picker.exec():
            return
        color = picker.selected_color()
        self.red_slider.setValue(color.red())
        self.green_slider.setValue(color.green())
        self.blue_slider.setValue(color.blue())
        self._apply_current_color()

    def _apply_current_color(self):
        if self._initializing:
            return
        self._color_apply_debounce.stop()
        self._effect_debounce.stop()
        color = self._current_color()
        self._ble.set_static_color(color.red(), color.green(), color.blue(), self.brightness_slider.value())
        self._aurora.set_accent_color(color.red(), color.green(), color.blue(), enabled=self.power_button.isChecked())
        self._remember_current_color()
        if self.effect_combo.currentData() != 0:
            with self._suppress_signals():
                self.effect_combo.setCurrentIndex(0)
            self._sync_effect_preview(reset_phase=True)
        self._sync_quick_mode_from_state()

    def _queue_current_color_update(self):
        if self._initializing:
            return
        color = self._current_color()
        self._aurora.set_accent_color(color.red(), color.green(), color.blue(), enabled=self.power_button.isChecked())
        if not self._is_connected:
            self._sync_quick_mode_from_state()
            return
        self._color_apply_debounce.start()

    def _toggle_power(self):
        self._sync_power_button()
        if self._initializing:
            return
        enabled = self.power_button.isChecked()
        self._ble.set_power(enabled)
        self._sync_aurora_accent(enabled=enabled)
        self._sync_quick_mode_from_state()

    def _sync_power_button(self):
        powered_on = self.power_button.isChecked()
        self.power_button.setText(self._tr("color.power_off") if powered_on else self._tr("color.power_on"))
        self.power_button.set_role("accent_soft" if powered_on else "ghost")

    def _sync_connect_buttons(self):
        connected = bool(self._is_connected)
        connecting = bool(self._connect_in_progress)
        has_devices = bool(self._devices)
        if connecting and not connected:
            if not self._connect_button_timer.isActive():
                self._connect_button_phase = 0
                self._connect_button_timer.start()
        elif self._connect_button_timer.isActive():
            self._connect_button_timer.stop()
        self.scan_button.setEnabled(not connected and not connecting and not self._scan_in_progress)
        self.connect_button.setVisible(not connected)
        self.connect_button.setEnabled(not connected and not connecting and has_devices and not self._scan_in_progress)
        self.connect_button.setText(self._connect_button_text() if connecting and not connected else self._tr("device.connect"))
        self.disconnect_button.setVisible(connected)
        self.disconnect_button.setEnabled(connected)
        self.logs_toggle_button.setVisible(connected)
        self.logs_toggle_button.setEnabled(connected)
        self.logs_toggle_button.setText(self._tr("device.show_logs"))

    def _connect_button_text(self) -> str:
        return f"{self._tr('device.connecting').rstrip('.')}{'.' * self._connect_button_phase}"

    def _tick_connect_button_animation(self) -> None:
        if not self._connect_in_progress or self._is_connected:
            self._connect_button_timer.stop()
            self._sync_connect_buttons()
            return
        self._connect_button_phase = (self._connect_button_phase + 1) % 4
        self.connect_button.setText(self._connect_button_text())

    def _apply_speed(self):
        if self._initializing:
            return
        self._ble.set_effect_speed(self.speed_slider.value())
        self._sync_quick_mode_from_state()

    def _queue_selected_effect(self):
        if self._initializing:
            return
        if self.effect_combo.currentData() is None:
            self._effect_debounce.stop()
            self._show_license_overlay()
            with self._suppress_signals():
                self.effect_combo.setCurrentIndex(self.effect_combo.findData(0))
            self._sync_effect_preview(reset_phase=True)
            return
        self._sync_effect_preview(reset_phase=True)
        self._sync_quick_mode_from_state()
        self._effect_debounce.start()

    def _apply_selected_effect(self):
        if self._initializing:
            return
        data = self.effect_combo.currentData()
        if data is None:
            self._show_license_overlay()
            with self._suppress_signals():
                self.effect_combo.setCurrentIndex(self.effect_combo.findData(0))
            self._sync_effect_preview(reset_phase=True)
            return
        code = int(data)
        if code == 0:
            self._ble.set_static_color(
                self.red_slider.value(),
                self.green_slider.value(),
                self.blue_slider.value(),
                self.brightness_slider.value(),
            )
            self._remember_current_color()
            self._log(self._tr("status.static_color_mode"))
            self._sync_effect_preview(reset_phase=True)
            self._sync_quick_mode_from_state()
            return
        self._ble.set_effect_with_speed(code, self.speed_slider.value())
        self._sync_effect_preview(reset_phase=True)
        self._sync_quick_mode_from_state()

    def _toggle_logs(self):
        self._show_logs_overlay()

    def _show_logs_overlay(self):
        labels = {
            "title": self._tr("logs.title"),
            "subtitle": self._tr("logs.subtitle"),
            "empty": self._tr("logs.empty"),
            "close": self._tr("dialog.ok"),
        }
        LogsOverlay(labels, self._ui_feedback.localized_log_text(), self).exec()

    def _check_for_updates_silent(self):
        self._update_controller.check_silent()

    def _check_for_updates(self):
        self._update_controller.check()

    def _handle_update_result(self, result: UpdateResult):
        self._update_controller.handle_result(result)

    def _open_update_page(self):
        self._update_controller.open_update_page()

    def _change_language(self):
        language = self.language_combo.currentData()
        if language == self.RELOAD_LANGUAGES_ACTION:
            self._reload_languages()
            return
        if not isinstance(language, str) or language == self._language:
            return
        snapshot = self.grab()
        self._language = language
        localization_manager.set_language(language)
        self._settings["language"] = language
        save_settings(self._settings)
        self.setWindowTitle(self._tr("dialog.title"))
        self._apply_localized_texts()
        self._refresh_localized_log_lines()
        self._theme_controller.sync_theme_button()
        self.preview.refresh_text()
        self._theme_controller.animate_overlay_fade(snapshot, duration=210)

    def _refresh_quick_mode_buttons(self):
        for key, button in self._mode_buttons.items():
            button.setText(self._tr(f"mode.{key}"))
            mode = QUICK_MODE_MAP.get(key)
            is_supported = True if mode is None else self._quick_mode_effect_code(mode) is not None
            button.setEnabled(is_supported or key == self._active_mode_key)
            button.set_role("mode_active" if key == self._active_mode_key else "mode")

    def _set_active_mode(self, mode_key: str | None, *, update_theme: bool = True):
        normalized = mode_key if mode_key in QUICK_MODE_MAP else None
        if normalized == self._active_mode_key:
            return
        self._active_mode_key = normalized
        self._settings["quick_mode"] = normalized or ""
        self._refresh_quick_mode_buttons()
        if update_theme:
            self._theme_controller.apply_theme()

    def _current_state_dict(self) -> dict:
        color = self._current_color()
        return {
            "power": self.power_button.isChecked(),
            "brightness": self.brightness_slider.value(),
            "speed": self.speed_slider.value(),
            "effect_code": int(self.effect_combo.currentData() or 0),
            "color": {"r": color.red(), "g": color.green(), "b": color.blue()},
        }

    def _sync_quick_mode_from_state(self, preferred: str | None = None):
        if self._initializing:
            return
        state = self._current_state_dict()
        preferred_mode = QUICK_MODE_MAP.get(preferred or "")
        if preferred_mode is not None and self._quick_mode_matches(preferred_mode, state):
            self._set_active_mode(preferred_mode.key)
            return
        active_mode = QUICK_MODE_MAP.get(self._active_mode_key or "")
        if active_mode is not None and not self._quick_mode_matches(active_mode, state):
            self._set_active_mode(None, update_theme=False)

    def _activate_quick_mode(self, mode_key: str):
        mode = QUICK_MODE_MAP.get(mode_key)
        if mode is None:
            return
        effect_code = self._quick_mode_effect_code(mode)
        if self._is_connected and effect_code is None:
            self._show_error(self._tr("error.effects_not_supported"))
            return
        self._set_active_mode(mode.key)
        payload = mode.as_profile()
        if effect_code is not None:
            payload["effect_code"] = effect_code
        color = payload.get("color", {})
        self._aurora.set_accent_color(
            int(color.get("r", 0)),
            int(color.get("g", 0)),
            int(color.get("b", 0)),
            enabled=bool(payload.get("power", True)),
        )
        self._profile_actions.apply_profile_payload(payload, announce_load=False)

    def _quick_mode_effect_code(self, mode) -> int | None:
        if mode.effect_code == 0 or self._ble.supports_effect_code(mode.effect_code):
            return mode.effect_code
        if mode.key != "rainbow":
            return None
        for effect in self._ble.effect_presets():
            if effect.key in {"smooth_rainbow", "smooth_spectrum", "triones_rainbow", "magic_home_rainbow"}:
                if self._ble.supports_effect_code(effect.code):
                    return effect.code
        return None

    def _quick_mode_matches(self, mode, state: dict) -> bool:
        if mode.matches(state):
            return True
        effect_code = self._quick_mode_effect_code(mode)
        if effect_code is None or effect_code == mode.effect_code:
            return False
        return (
            bool(state.get("power")) == mode.power
            and int(state.get("brightness", -1)) == mode.brightness
            and int(state.get("effect_code", -1)) == effect_code
            and int(state.get("speed", -1)) == mode.speed
        )

    def _collect_state(self, name):
        color = self._current_color()
        return ProfileState(
            name=name,
            power=self.power_button.isChecked(),
            brightness=self.brightness_slider.value(),
            speed=self.speed_slider.value(),
            effect_code=int(self.effect_combo.currentData() or 0),
            schedule=self._schedule_ctrl.settings(),
            color={"r": color.red(), "g": color.green(), "b": color.blue()},
        )

    def _refresh_profiles(self):
        self._profile_controller.refresh_list(self.profile_list)

    def _show_error(self, message):
        self._ble_events.show_error(message)
        self._refresh_diagnostics_view()

    def _log(self, message):
        self._ble_events.log(message)
        self._refresh_diagnostics_view()

    def _diagnostics_text(self) -> str:
        return build_diagnostics_report(
            self._ble.diagnostics_snapshot(),
            self._ui_feedback.raw_log_messages(),
            include_crashes=False,
        )

    def _refresh_diagnostics_view(self):
        if self.diagnostics_output is not None and self._ui_feedback is not None:
            self.diagnostics_output.setPlainText(self._diagnostics_text())

    def _copy_diagnostics_report(self):
        QApplication.clipboard().setText(self._diagnostics_text())
        self._log(self._tr("diagnostics.copied"))

    def _export_diagnostics_report(self):
        default_name = f"lumable-diagnostics-{APP_VERSION}.txt"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            self._tr("diagnostics.export_title"),
            str(Path.home() / "Desktop" / default_name),
            self._tr("diagnostics.file_filter"),
        )
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        report = build_diagnostics_report(
            self._ble.diagnostics_snapshot(),
            self._ui_feedback.raw_log_messages(),
            include_crashes=True,
        )
        try:
            Path(path).write_text(report, encoding="utf-8")
        except OSError as exc:
            self._show_error(self._tr("diagnostics.export_error", error=str(exc)))
            return
        self._log(self._tr("diagnostics.exported", path=Path(path).name))

    def _save_window_settings(self):
        self._settings["window_width"] = self.width()
        self._settings["window_height"] = self.height()
        self._settings["language"] = self._language
        self._settings["theme_mode"] = self._theme_mode
        self._settings["theme"] = "dark" if self._is_dark else "light"
        self._settings["capture_compatibility"] = bool(self._settings.get("capture_compatibility", True))
        self._settings["quick_mode"] = self._active_mode_key or ""
        self._settings["color_history"] = self._color_history()[: 12 if can_use("color_history_full") else 3]
        self._settings["schedule"] = self._schedule_ctrl.settings()
        last_state = asdict(self._collect_state("last"))
        last_state.pop("schedule", None)
        self._settings["last_state"] = last_state
        save_settings(self._settings)

    def _finish_close_after_ble_shutdown(self):
        self._close_after_ble_shutdown = True
        QTimer.singleShot(0, self.close)

    def _force_close(self):
        if not self._close_requested or self._close_after_ble_shutdown:
            return
        self._close_after_ble_shutdown = True
        self.close()

    def closeEvent(self, event):
        try:
            self._save_window_settings()
        except Exception:
            pass
        if self._tray_controller.should_minimize_on_close():
            event.ignore()
            self.hide()
            self._tray_controller.show_notice_once()
            return
        if self._close_after_ble_shutdown:
            self._tray_controller.hide_icon()
            super().closeEvent(event)
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(0, app.quit)
            return
        event.ignore()
        if self._close_requested:
            return
        self._close_requested = True
        self.setEnabled(False)
        if getattr(self._ble, "_shutdown_started", False):
            self._finish_close_after_ble_shutdown()
            return
        self._ble.shutdown_async()
        QTimer.singleShot(3000, self._force_close)


def run():
    QCoreApplication.setOrganizationName(APP_ORGANIZATION)
    QCoreApplication.setApplicationName(localization_manager.t("dialog.title"))
    QCoreApplication.setApplicationVersion(APP_VERSION)
    app = QApplication(sys.argv)
    icon_path = Path(__file__).resolve().parent / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())

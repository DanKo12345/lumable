from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEasingCurve,
    QPropertyAnimation,
    QSignalBlocker,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTextEdit,
)

from app.ambient_ui_controller import AmbientUiController
from app.app_info import APP_ORGANIZATION, APP_RELEASES_URL, APP_UPDATE_URL, APP_VERSION
from app.app_trigger_controller import AppTriggerController
from app.app_trigger_ui_controller import AppTriggerUiController
from app.automation.controller import AutomationController, schedule_first_sync
from app.automation_ui_controller import AutomationUiController
from app.ble import BleController
from app.ble_event_handler import BleEventHandler
from app.color_controller import ColorController
from app.color_temperature import cct_to_rgb
from app.constants import (
    CHIP_HEIGHT,
    COMPACT_SIDEBAR_HEIGHT,
    CONTROL_HEIGHT,
    SLIDER_LABEL_WIDTH,
    SLIDER_ROW_MARGINS,
    SLIDER_ROW_SPACING,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from app.diagnostics_controller import DiagnosticsController
from app.diy_ui_controller import DiyUiController
from app.feature_gate import FREE_COLOR_HISTORY_COUNT, PRO_COLOR_HISTORY_COUNT, can_use
from app.hotkey_controller import HotkeyController
from app.hotkey_ui_controller import HotkeyUiController
from app.license_refresh import LicenseRefresher
from app.local_api.controller import LocalApiController
from app.localization import localization_manager
from app.main_layout import build_main_layout
from app.motion_policy import DEFAULT_MOTION_MODE, motion_policy
from app.music_ui_controller import MusicUiController
from app.overlay_controller import OverlayController
from app.performance import resolve_ui_fps
from app.profile_actions import ProfileActions
from app.profile_controller import ProfileController
from app.quick_mode_controller import QuickModeController
from app.reconnect_controller import ReconnectController
from app.scene_presets import get_scene_preset
from app.scene_ui_controller import SceneUiController
from app.schedule_controller import ScheduleController
from app.shortcut_controller import ShortcutController
from app.single_instance import SingleInstance
from app.software_effect_ui_controller import SoftwareEffectUiController
from app.storage import (
    DEFAULT_START_COLOR,
    load_profiles,
    load_settings,
    save_settings,
    update_power_setting,
)
from app.theme import theme_manager
from app.theme_controller import ThemeController
from app.timer_controller import TimerController
from app.tray_controller import TrayController
from app.ui_feedback import UiFeedback
from app.ui_localization_controller import UiLocalizationController
from app.ui_scale import resolve_ui_scale
from app.update_checker import UpdateResult
from app.update_controller import UpdateController
from app.widgets import (
    AuroraBackground,
    ColorPickerOverlay,
    GlassCard,
    LiquidButton,
    LiquidSlider,
    LogsOverlay,
    ProfileConfirmOverlay,
    ProfileRenameOverlay,
    SmoothScrollFilter,
    ValueChip,
)
from app.widgets.onboarding_overlay import OnboardingOverlay
from app.widgets.styled_tooltip import TooltipManager
from app.window_state_controller import WindowStateController
from app.windows_motion import windows_motion_reduced


def _startup_services_disabled() -> bool:
    """Deferred startup services are skipped when this is set.

    The test suite sets it: autoconnect, the license refresh, app triggers,
    hotkeys, the silent update check and the local API are all exercised
    directly against their controllers, so scheduling them from a widget test
    only adds background work — and their pending timers hold a bound method of
    the window, which keeps every closed window (and its ~600 widgets) alive for
    the rest of the process.
    """
    return os.environ.get("LUMABLE_NO_STARTUP_SERVICES", "").strip().lower() in {"1", "true", "yes"}


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
        self._apply_ui_fps()
        self._wire_events()
        self._load_initial_state()
        self._tray_controller.setup()
        self._apply_windows_backdrop()
        self._schedule_ctrl.start()
        self._timer_ctrl.start()
        self._tooltip_manager = TooltipManager(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._tooltip_manager)
        self._start_deferred(300, self.maybe_show_onboarding)
        self._start_deferred(500, self._ble_events.start_autoconnect)
        self._start_deferred(900, self._license_refresher.refresh)
        self._start_deferred(1300, self._app_triggers.start)
        self._start_deferred(1400, self._apply_hotkeys)
        self._start_deferred(1600, self._update_controller.check_silent)
        self._start_deferred(1800, self._local_api.start)
        # Order matters here. The migration is what switches the old App Trigger
        # watcher off, so the engine that takes over from it has to be running
        # before that happens — and the Windows tasks are reconciled last, against
        # the rules the migration has by then written.
        self._start_deferred(2000, self._start_automations)

    def _sz(self, value: float) -> int:
        """Scale a base pixel size by the current UI-density factor."""
        return max(1, round(value * getattr(self, "_ui_scale", 1.0)))

    def _init_state(self) -> None:
        """Initialise plain data attributes before any controller is created."""
        self._ui_scale = resolve_ui_scale(QApplication.primaryScreen())
        self._control_height = self._sz(CONTROL_HEIGHT)
        self._chip_height = self._sz(CHIP_HEIGHT)
        self._settings = load_settings()
        self._theme_mode = self._settings.get("theme_mode") or self._settings.get("theme", "dark")
        self._language = self._settings.get("language", "ru")
        localization_manager.set_language(self._language)
        if self._theme_mode not in {"dark", "light", "auto"}:
            self._theme_mode = "auto"
        self._is_dark = ThemeController.resolve_dark_from_mode(self._theme_mode)
        self._theme_tokens = theme_manager.set_dark(self._is_dark)
        self._profiles = load_profiles()
        self._custom_quick_modes: list[dict] = list(self._settings.get("custom_quick_modes", []))
        self._devices: list = []
        self._is_connected = False
        self._initializing = False
        self._close_after_ble_shutdown = False
        self._close_requested = False
        self._force_quit_requested = False
        self._scan_in_progress = False
        self._connect_in_progress = False
        self._connection_status_phase = 0
        self._status_pulsing = False
        self._focus_follow_wired = False
        motion_policy.changed.connect(self._on_motion_changed)
        self._reconnecting = False
        self._active_mode_key: str | None = None
        self._theme_transition = None
        self._theme_transition_overlay = None
        self._update_result: UpdateResult | None = None
        self._color_picker_overlay: ColorPickerOverlay | None = None
        self._slider_value_overlay: ProfileRenameOverlay | None = None
        self._custom_quick_overlay = None
        self._logs_overlay: LogsOverlay | None = None
        # Widget refs set later by _build_ui / build_main_layout
        self.diagnostics_output = None
        self._ui_feedback = None
        self._buttons: list[LiquidButton] = []
        self._slider_labels: dict[str, QLabel] = {}
        self._slider_rows: dict[str, tuple] = {}  # key -> (slider, value chip)
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
        self._timer_ctrl = TimerController(self)
        self._quick_mode_ctrl = QuickModeController(self)
        self._ambient_ui = AmbientUiController(self)
        self._music_ui = MusicUiController(self)
        self._software_fx_ui = SoftwareEffectUiController(self)
        self._diy_ui = DiyUiController(self)
        self._scene_ui = SceneUiController(self)
        self._app_trigger_ui = AppTriggerUiController(self)
        self._app_triggers = AppTriggerController(self)
        self._hotkey_controller = HotkeyController(self)
        self._hotkey_ui = HotkeyUiController(self)
        self._window_state = WindowStateController(self)
        self._diagnostics_ctrl = DiagnosticsController(self)
        self._reconnect_ctrl = ReconnectController(self)
        self._local_api = LocalApiController(self)
        self._color_ctrl = ColorController(self)
        self._license_refresher = LicenseRefresher(self)
        self._license_refresher.finished.connect(self._on_license_refreshed)
        # Everything about automations behind one object: the engine, the migration,
        # the Windows tasks and the journal. The window asks it for what it needs and
        # is told when something has been applied.
        self._automations = AutomationController(self, lambda: self._local_api.backend(), parent=self)
        self._automations.applied.connect(self._reflect_automation_state)
        self._automation_ui = AutomationUiController(self)
        self._aurora = AuroraBackground(self)

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

        self._local_color_debounce = QTimer(self)
        self._local_color_debounce.setSingleShot(True)
        self._local_color_debounce.setInterval(120)
        self._local_color_debounce.timeout.connect(self._apply_local_current_color)

        self._connection_status_timer = QTimer(self)
        self._connection_status_timer.setInterval(450)
        self._connection_status_timer.timeout.connect(self._tick_connection_status_animation)

        # Re-resolve "auto" UI fps periodically so unplugging the laptop drops to
        # the battery-friendly rate (and plugging in restores the smooth rate).
        self._ui_fps_timer = QTimer(self)
        self._ui_fps_timer.setInterval(20_000)
        self._ui_fps_timer.timeout.connect(self._apply_ui_fps)
        self._ui_fps_timer.start()

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
        shell_layout = QGridLayout(self._aurora)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(root, 0, 0)
        self._aurora.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._apply_localized_texts()
        self._install_smooth_scroll(self.profile_list, step=46, duration=105)
        self._install_smooth_scroll(self.diagnostics_output, step=54, duration=185)
        self._install_smooth_scroll(self.body_scroll, step=72, duration=210)
        self.log_output = QTextEdit(self)
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.hide()
        self._ui_feedback = UiFeedback(self, self.log_output, lambda: self._theme_tokens, self._tr)
        self.setCentralWidget(self._aurora)

    def _apply_localized_texts(self):
        self._ui_localization.apply_texts()

    def _show_about_overlay(self) -> None:
        self._overlay_controller.show_about()

    def _show_update_overlay(self, info) -> None:
        self._overlay_controller.show_update(info)

    def _show_license_overlay(self) -> None:
        self._overlay_controller.show_license()

    def _offer_protocol_candidate(self, address: str, driver_id: str, driver_name: str) -> None:
        """An unrecognised controller looks like a known driver — ask before
        trying it (we never send anything until the user agrees)."""
        if getattr(self, "_protocol_offer_overlay", None) is not None:
            return
        labels = {
            "title": self._tr("protocol.offer_title"),
            "message": self._tr("protocol.offer_message", driver=driver_name),
            "cancel": self._tr("dialog.cancel"),
            "confirm": self._tr("protocol.try"),
        }
        overlay = ProfileConfirmOverlay(labels, self)
        self._protocol_offer_overlay = overlay
        overlay.confirmed.connect(lambda a=address, d=driver_id: self._try_forced_driver(a, d))
        overlay.closed.connect(lambda: setattr(self, "_protocol_offer_overlay", None))
        overlay.open()

    def _try_forced_driver(self, address: str, driver_id: str) -> None:
        self._log(self._tr("protocol.trying_log"))
        self._ble.connect_to_address(address, force_driver_id=driver_id)

    def _rename_primary_device(self) -> None:
        address = str(self._settings.get("last_device_address", "")).strip()
        if address:
            self._ble_events.rename_device(address)

    # ── first-run onboarding ──────────────────────────────────────────
    def maybe_show_onboarding(self) -> None:
        """Show the welcome carousel once, on the very first launch."""
        if isinstance(self._settings, dict) and self._settings.get("onboarding_seen"):
            return
        self.show_onboarding()

    def show_onboarding(self) -> None:
        if getattr(self, "_onboarding_overlay", None) is not None:
            self._onboarding_overlay.raise_()
            return
        overlay = OnboardingOverlay(self._onboarding_labels(), self)
        self._onboarding_overlay = overlay
        overlay.scanRequested.connect(self._ble_events.start_scan)
        overlay.finished.connect(self._on_onboarding_finished)
        overlay.open()

    def _on_onboarding_finished(self) -> None:
        self._onboarding_overlay = None
        if isinstance(self._settings, dict) and not self._settings.get("onboarding_seen"):
            self._settings["onboarding_seen"] = True
            save_settings(self._settings)

    def _onboarding_labels(self) -> dict:
        tr = self._tr
        return {
            "skip": tr("onboarding.skip"),
            "back": tr("onboarding.back"),
            "next": tr("onboarding.next"),
            "finish": tr("onboarding.finish"),
            "scan": tr("onboarding.scan"),
            "steps": [
                {"icon": "app", "title": tr("onboarding.welcome_title"), "body": tr("onboarding.welcome_body")},
                {"icon": "device", "title": tr("onboarding.connect_title"), "body": tr("onboarding.connect_body"), "scan": True},
                {"icon": "effects", "title": tr("onboarding.sections_title"), "body": tr("onboarding.sections_body")},
                {"icon": "sparkle", "title": tr("onboarding.pro_title"), "body": tr("onboarding.pro_body")},
                {"icon": "check", "title": tr("onboarding.done_title"), "body": tr("onboarding.done_body")},
            ],
        }

    def _on_license_refreshed(self, is_pro_now: bool, changed: bool) -> None:
        """React to a background license revalidation finishing."""
        if not changed:
            return
        self._apply_localized_texts()
        self._refresh_color_history()
        self._apply_hotkeys()
        self._log(self._tr("license.activated_log") if is_pro_now else self._tr("license.expired_log"))

    def _apply_hotkeys(self) -> None:
        config = self._settings.get("hotkeys", {}) if isinstance(self._settings, dict) else {}
        config = config if isinstance(config, dict) else {}
        bindings = config.get("bindings", {})
        bindings = bindings if isinstance(bindings, dict) else {}
        enabled = bool(config.get("enabled", False))
        self._hotkey_controller.apply(bindings, enabled=enabled)

    def _refresh_effect_names(self):
        self._color_ctrl.refresh_effect_names()

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
        # Single choke point for re-translation, so the slider and its readout
        # follow the new language instead of announcing the old one.
        row = self._slider_rows.get(key)
        if row is not None:
            slider, value = row
            slider.setAccessibleName(text)
            value.set_purpose(text)

    def _card(self, title: str, subtitle: str | None = None, icon: str | None = None) -> GlassCard:
        return GlassCard(title, subtitle, icon=icon)

    def _button(self, text: str, role: str) -> LiquidButton:
        button = LiquidButton(text, role)
        font = button.font()
        font.setPointSizeF(11.0 * self._ui_scale)
        font.setWeight(QFont.Weight.DemiBold)
        button.setFont(font)
        self._buttons.append(button)
        return button

    def _slider(self, accent: str) -> LiquidSlider:
        slider = LiquidSlider(accent)
        slider.set_render_scale(self._ui_scale)
        return slider

    def _pill(self, text: str) -> ValueChip:
        label = ValueChip(text)
        label.setMinimumWidth(self._sz(68))
        label.setMinimumHeight(self._chip_height)
        return label

    def _slider_row(self, name: str, slider: LiquidSlider, value: ValueChip, key: str | None = None):
        layout = QHBoxLayout()
        layout.setSpacing(SLIDER_ROW_SPACING)
        layout.setContentsMargins(*SLIDER_ROW_MARGINS)
        label = QLabel(name)
        label.setObjectName("sliderLabel")
        label.setFixedWidth(self._sz(SLIDER_LABEL_WIDTH))
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if key is not None:
            self._slider_labels[key] = label
            self._slider_rows[key] = (slider, value)
        # The row label and the readout are separate widgets; tell the chip what
        # it stands for so it announces "Brightness: 50%", not a bare "50%".
        value.set_purpose(name)
        slider.setAccessibleName(name)
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        # Centred, so the chip keeps its own compact height instead of
        # stretching to the full (slider-driven) row height.
        layout.addWidget(value, 0, Qt.AlignVCenter)
        return layout

    def _install_smooth_scroll(self, widget, step: int = 58, duration: int = 180):
        viewport = widget.viewport() if hasattr(widget, "viewport") else widget
        scroll_filter = SmoothScrollFilter(widget, step=step, duration=duration)
        viewport.installEventFilter(scroll_filter)
        self._scroll_filters.append(scroll_filter)

    def _keep_focus_in_view(self, _old, new) -> None:
        """Scroll the content page so the focused control stays on screen.

        Tab can move focus to a control below the fold, leaving the focus ring
        somewhere the user cannot see. ``ensureWidgetVisible`` is a no-op when
        the widget is already visible, so mouse-driven focus is unaffected.
        """
        if new is None:
            return
        page = self.body_scroll.widget()
        if page is None or not self.body_scroll.isVisible():
            return
        if new is not page and not page.isAncestorOf(new):
            return  # focus went to the sidebar, an overlay or the window chrome
        self.body_scroll.ensureWidgetVisible(new, 0, 40)

    def showEvent(self, event):
        super().showEvent(event)
        self._set_focus_follow(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._set_focus_follow(False)

    def _set_focus_follow(self, enabled: bool) -> None:
        """Subscribe to the app-wide focus signal only while this window is up.

        ``focusChanged`` lives on the QApplication, so a permanent subscription
        from every window that was ever built would keep handing every focus
        change to windows that are no longer on screen.
        """
        app = QApplication.instance()
        if app is None or enabled == self._focus_follow_wired:
            return
        if enabled:
            app.focusChanged.connect(self._keep_focus_in_view)
        else:
            app.focusChanged.disconnect(self._keep_focus_in_view)
        self._focus_follow_wired = enabled

    def _wire_events(self):
        self._wire_device_events()
        self._wire_theme_events()
        self._wire_color_events()
        self._wire_profile_events()
        self._wire_ble_events()
        self._wire_update_events()
        self._wire_diagnostics_events()
        self._wire_schedule_events()
        self._ambient_ui.wire()
        self._music_ui.wire()
        self._software_fx_ui.wire()
        self._diy_ui.wire()
        self._scene_ui.wire()
        self._app_trigger_ui.wire()
        self._automation_ui.wire()
        self._hotkey_ui.wire()
        self._local_api.wire()
        # Manual power and PC-mode starts (screen sync, music, software FX, DIY)
        # also mean the strip no longer shows the applied scene.
        for scene_breaker in (
            self.power_button,
            self.ambient_toggle_button,
            self.music_toggle_button,
            self.software_fx_toggle,
            self.diy_run_button,
        ):
            scene_breaker.clicked.connect(self._note_manual_scene_change)
        self._wire_shortcuts()

    def _wire_device_events(self):
        self.scan_button.clicked.connect(self._ble_events.start_scan)
        self.connect_button.clicked.connect(self._ble_events.handle_connect)
        self.disconnect_button.clicked.connect(self._ble.disconnect)
        self.add_mirror_button.clicked.connect(self._ble_events.request_add_mirror)
        self.logs_toggle_button.clicked.connect(self._show_logs_overlay)
        self.supported_controllers_button.clicked.connect(self._show_about_overlay)
        self.rename_device_button.clicked.connect(self._rename_primary_device)

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
        self.performance_combo.currentIndexChanged.connect(self._change_performance)
        self.motion_combo.currentIndexChanged.connect(self._change_motion_mode)

    def _apply_ui_fps(self) -> None:
        fps = resolve_ui_fps(self._settings.get("ui_fps", "auto"))
        self._aurora.set_target_fps(fps)
        if self.effect_preview is not None:
            self.effect_preview.set_target_fps(fps)

    def _change_performance(self):
        mode = self.performance_combo.currentData()
        if not mode:
            return
        self._settings["ui_fps"] = str(mode)
        save_settings(self._settings)
        self._apply_ui_fps()

    def _change_motion_mode(self):
        mode = self.motion_combo.currentData()
        if not mode:
            return
        motion_policy.set_mode(mode)  # applies immediately; open windows react to changed
        self._settings["motion_mode"] = str(mode)
        save_settings(self._settings)

    def _wire_color_events(self):
        self.pick_color_button.clicked.connect(self._pick_color)
        self.power_button.clicked.connect(self._toggle_power)
        self.effect_combo.currentIndexChanged.connect(self._queue_selected_effect)
        self.speed_slider.valueChanged.connect(lambda v: self.speed_value.setText(f"{v}%"))
        self.speed_slider.valueChanged.connect(self.effect_preview.set_speed)
        self.speed_slider.sliderReleased.connect(self._apply_speed)
        self.speed_value.clicked.connect(lambda: self._edit_slider_value(self.speed_slider, self.speed_value, suffix="%"))
        for index, button in enumerate(self.color_history_buttons):
            button.clicked.connect(lambda _checked=False, swatch_index=index: self._apply_color_history_item(swatch_index))
        self._wire_rgb_slider_events()
        self.brightness_slider.valueChanged.connect(lambda v: self.brightness_value.setText(f"{v}%"))
        self.brightness_slider.valueChanged.connect(self.preview.set_brightness)
        self.brightness_slider.valueChanged.connect(self._queue_current_color_update)
        self.brightness_value.clicked.connect(
            lambda: self._edit_slider_value(self.brightness_slider, self.brightness_value, suffix="%")
        )
        self.temperature_slider.valueChanged.connect(self._on_temperature_changed)
        self.temperature_value.clicked.connect(
            lambda: self._edit_slider_value(self.temperature_slider, self.temperature_value, suffix="K")
        )
        # Any hand-made change to the light means the strip no longer shows the
        # applied scene — drop the tile highlight (the scene controller ignores
        # the programmatic echoes of its own apply).
        for slider in (
            self.red_slider,
            self.green_slider,
            self.blue_slider,
            self.brightness_slider,
            self.temperature_slider,
        ):
            slider.valueChanged.connect(self._note_manual_scene_change)
        self.effect_combo.currentIndexChanged.connect(self._note_manual_scene_change)

    def _wire_rgb_slider_events(self):
        for slider, label in (
            (self.red_slider, self.red_value),
            (self.green_slider, self.green_value),
            (self.blue_slider, self.blue_value),
        ):
            slider.valueChanged.connect(lambda v, t=label: t.setText(str(v)))
            # clicked carries a bool; it must land in _checked, not in the
            # captured slider, or the editor would be handed False.
            label.clicked.connect(
                lambda _checked=False, s=slider, value_chip=label: self._edit_slider_value(s, value_chip)
            )
            slider.valueChanged.connect(self._update_preview)
            slider.valueChanged.connect(self._queue_current_color_update)

    def _edit_slider_value(self, slider: LiquidSlider, value_label: ValueChip, *, suffix: str = ""):
        if self._slider_value_overlay is not None:
            self._slider_value_overlay.raise_()
            return
        overlay = ProfileRenameOverlay(
            {
                "title": self._tr("dialog.slider_value_title"),
                "prompt": self._tr("dialog.slider_value_label"),
                "cancel": self._tr("dialog.cancel"),
                "ok": self._tr("dialog.ok"),
            },
            str(slider.value()),
            self,
        )
        self._slider_value_overlay = overlay
        overlay.nameSelected.connect(
            lambda text: self._apply_slider_value_text(slider, value_label, suffix, text)
        )
        overlay.closed.connect(lambda: setattr(self, "_slider_value_overlay", None))
        overlay.open()

    def _apply_slider_value_text(self, slider: LiquidSlider, value_label: ValueChip, suffix: str, text: str):
        try:
            value = round(float(text.replace(",", ".")))
        except ValueError:
            return
        value = max(slider.minimum(), min(slider.maximum(), value))
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
        self._ble.mirrors_changed.connect(self._ble_events.refresh_mirror_list)
        self._ble.primary_changed.connect(self._ble_events.on_primary_changed)
        self._ble.protocol_candidate_found.connect(self._offer_protocol_candidate)
        self._reconnect_ctrl.wire()
        self._ble.error_occurred.connect(self._show_error)
        self._ble.shutdown_finished.connect(self._finish_close_after_ble_shutdown)

    def _wire_update_events(self):
        self._update_controller.wire()

    def _wire_diagnostics_events(self):
        self.copy_diagnostics_button.clicked.connect(self._copy_diagnostics_report)
        self.report_device_button.clicked.connect(self._report_unsupported_device)
        self.export_diagnostics_button.clicked.connect(self._export_diagnostics_report)
        self.show_logs_button.clicked.connect(self._show_logs_overlay)

    def _wire_schedule_events(self):
        self._schedule_ctrl.wire()
        self._timer_ctrl.wire()

    def _toggle_schedule(self, _checked: bool = False) -> None:
        self._schedule_ctrl.toggle_schedule(_checked)

    def _sync_schedule_controls(self) -> None:
        self._schedule_ctrl.sync_controls()

    def _check_schedule(self) -> None:
        self._schedule_ctrl._check_schedule()

    def _load_initial_state(self):
        self._restore_startup_size()
        self._apply_compact_sidebar()  # a restored small size may need it before first resize
        last = self._settings.get("last_state", {})
        color = last.get("color", DEFAULT_START_COLOR)
        with self._suppress_signals():
            self.red_slider.setValue(int(color.get("r", DEFAULT_START_COLOR["r"])))
            self.green_slider.setValue(int(color.get("g", DEFAULT_START_COLOR["g"])))
            self.blue_slider.setValue(int(color.get("b", DEFAULT_START_COLOR["b"])))
            self.brightness_slider.setValue(int(last.get("brightness", 100)))
            self.temperature_slider.setValue(int(self._settings.get("color_temperature", 4500)))
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
        self._apply_compact_sidebar()

    def _apply_compact_sidebar(self) -> None:
        # On a short window the sidebar can't fit its full-height footer, so drop
        # the secondary status hint and shrink the status card. The primary
        # status and all nav items stay — nothing is hidden that isn't redundant.
        compact = self.height() < COMPACT_SIDEBAR_HEIGHT
        if compact == getattr(self, "_sidebar_compact", None):
            return
        self._sidebar_compact = compact
        card = getattr(self, "device_status_card", None)
        if card is not None:
            card.setMinimumHeight(self._sz(32 if compact else 56))
        self._set_status_hint_visible(getattr(self, "_status_hint_wanted", True))

    def _set_status_hint_visible(self, wanted: bool) -> None:
        # Single source for the secondary status line's visibility: the
        # connection state decides whether it is *wanted*, but the compact
        # sidebar overrides it so the primary status never clips off the bottom.
        self._status_hint_wanted = wanted
        hint = getattr(self, "device_status_hint", None)
        if hint is not None:
            hint.setVisible(wanted and not getattr(self, "_sidebar_compact", False))

    def _apply_windows_backdrop(self):
        self._window_state.apply_windows_backdrop()

    def _current_color(self):
        return QColor(self.red_slider.value(), self.green_slider.value(), self.blue_slider.value())

    def _update_preview(self):
        self.preview.set_color(self._current_color())

    def _sync_aurora_accent(self, *, enabled: bool | None = None) -> None:
        # Background mechanic (as in v0.2.0): the strip colour glows over the
        # graphite base while the strip is on. An explicit power-off returns the
        # backdrop to neutral graphite; changing a colour always re-lights it.
        color = self._current_color()
        active = self.power_button.isChecked() if enabled is None else bool(enabled)
        theme_manager.led_glow = QColor(color)
        self._aurora.set_accent_color(color.red(), color.green(), color.blue(), enabled=active)
        self.power_button.set_led_color(QColor(color))

    def _color_history(self) -> list[dict[str, int]]:
        return self._color_ctrl.color_history()

    def _refresh_color_history(self) -> None:
        self._color_ctrl.refresh_history()

    def _remember_current_color(self) -> None:
        self._color_ctrl.remember_current()

    def _apply_color_history_item(self, index: int) -> None:
        self._color_ctrl.apply_history_item(index)

    def _sync_effect_preview(self, *, reset_phase: bool = False):
        self._color_ctrl.sync_effect_preview(reset_phase=reset_phase)

    def _sync_speed_controls(self):
        self._color_ctrl.sync_speed_controls()

    def _pick_color(self):
        if self._color_picker_overlay is not None:
            self._color_picker_overlay.raise_()
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
        self._color_picker_overlay = picker
        picker.colorSelected.connect(self._apply_picked_color)
        picker.closed.connect(lambda: setattr(self, "_color_picker_overlay", None))
        picker.open()

    def _apply_picked_color(self, color: QColor) -> None:
        self.red_slider.setValue(color.red())
        self.green_slider.setValue(color.green())
        self.blue_slider.setValue(color.blue())
        self._apply_current_color()

    def _apply_scene_preset(self, key: str) -> None:
        preset = get_scene_preset(key)
        if preset is None:
            return
        red, green, blue = preset.rgb
        with self._suppress_signals():
            self.red_slider.setValue(red)
            self.green_slider.setValue(green)
            self.blue_slider.setValue(blue)
            self.brightness_slider.setValue(preset.brightness)
            static_index = self.effect_combo.findData(0)
            if static_index >= 0:
                self.effect_combo.setCurrentIndex(static_index)
            self._update_preview()
        # Turn the strip on so the scene is visible, then apply (the colour glides
        # in via the fade path).
        if self._is_connected and not self.power_button.isChecked():
            self.power_button.setChecked(True)
            self._toggle_power()
        self._apply_current_color()
        self._remember_current_color()
        self._sync_quick_mode_from_state()
        self._log(self._tr("presets.applied", name=self._tr(f"scene.{key}")))

    def _on_temperature_changed(self, kelvin: int) -> None:
        # Warm↔cool white: map the Kelvin value to an RGB point and drive the
        # colour sliders, then apply along the normal colour path (with fade).
        self.temperature_value.setText(f"{int(kelvin)}K")
        if self._initializing:
            return
        red, green, blue = cct_to_rgb(int(kelvin))
        with self._suppress_signals():
            self.red_slider.setValue(red)
            self.green_slider.setValue(green)
            self.blue_slider.setValue(blue)
            self._update_preview()
        self._apply_current_color()
        self._remember_current_color()
        if isinstance(self._settings, dict):
            self._settings["color_temperature"] = int(kelvin)
            self._persist_settings()

    def _apply_current_color(self):
        if self._initializing:
            return
        self._update_preview()
        self._color_apply_debounce.stop()
        self._local_color_debounce.stop()
        self._effect_debounce.stop()
        color = self._current_color()
        if not self._is_connected:
            self._apply_local_color_state(color)
            return
        brightness = self.brightness_slider.value()
        if bool(self._settings.get("fade", True)):
            # Big scene jumps glide; the BLE layer snaps small slider nudges.
            self._ble.set_color_fade(color.red(), color.green(), color.blue(), brightness)
        else:
            self._ble.set_static_color(color.red(), color.green(), color.blue(), brightness)
        self._apply_local_color_state(color)

    def _apply_local_current_color(self):
        if self._initializing:
            return
        self._update_preview()
        self._apply_local_color_state(self._current_color())

    def _apply_local_color_state(self, color: QColor):
        # Applying a colour always lights the strip (the command is sent even
        # when the power toggle is "off"), so the Lumen glow must follow the
        # colour here regardless of the toggle. Only an explicit power-off
        # (_toggle_power) returns the backdrop to neutral.
        theme_manager.led_glow = QColor(color)
        self._aurora.set_accent_color(color.red(), color.green(), color.blue(), enabled=True)
        self.power_button.set_led_color(QColor(color))
        self._remember_current_color()
        if self.effect_combo.currentData() != 0:
            with self._suppress_signals():
                self.effect_combo.setCurrentIndex(0)
            self._sync_effect_preview(reset_phase=True)
        self._sync_quick_mode_from_state()

    def _queue_current_color_update(self):
        if self._initializing:
            return
        if not self._is_connected:
            self._local_color_debounce.start()
            return
        self._color_apply_debounce.start()

    def _stream_owners(self) -> tuple:
        """Every controller that can drive the strip's colour path. Exactly one
        of these owns the strip at a time; starting one stops the rest."""
        return (
            self._ambient_ui,
            self._music_ui,
            self._software_fx_ui,
            self._diy_ui,
            self._timer_ctrl,
        )

    def stop_streams(self, *, exclude: object | None = None) -> None:
        """Stop every streaming owner except `exclude` (the one taking over)."""
        for owner in self._stream_owners():
            if owner is None or owner is exclude:
                continue
            stop = getattr(owner, "stop_if_running", None)
            if callable(stop):
                stop()

    def stop_all_streams(self) -> None:
        """Stop every streaming owner — used when the strip goes away (BLE drop)."""
        self.stop_streams()

    def _toggle_power(self):
        self._sync_power_button()
        if self._initializing:
            return
        # Power is a manual override: any running stream yields the strip.
        self.stop_streams()
        enabled = self.power_button.isChecked()
        self._ble.set_power(enabled)
        self._remember_power_setting(enabled)
        self._sync_aurora_accent(enabled=enabled)
        self._sync_quick_mode_from_state()

    def _remember_power_setting(self, enabled: bool) -> None:
        """Persist only power, without saving the window's stale settings copy."""

        power = bool(enabled)
        self._settings.setdefault("last_state", {})["power"] = power
        try:
            update_power_setting(power)
        except (OSError, TimeoutError):
            # The UI state remains authoritative for this process and closeEvent
            # will still save every unrelated setting. A busy settings file must
            # never be bypassed with an unsafe concurrent write.
            pass

    def _sync_power_button(self):
        powered_on = self.power_button.isChecked()
        self.power_button.setText(self._tr("color.power_off") if powered_on else self._tr("color.power_on"))
        # When lit, the main action carries the current strip colour ("your
        # light"); when the strip is off it falls back to a neutral glass look.
        self.power_button.set_role("led" if powered_on else "ghost")

    def _sync_connect_buttons(self):
        connected = bool(self._is_connected)
        connecting = bool(self._connect_in_progress)
        has_devices = bool(self._devices)
        # Animate the "…" on both the scanning and connecting status text.
        active = (connecting or self._scan_in_progress) and not connected
        if active:
            if not self._connection_status_timer.isActive():
                self._connection_status_phase = 0
                self._connection_status_timer.start()
            self.device_status.setText(self._connection_status_text())
        elif self._connection_status_timer.isActive():
            self._connection_status_timer.stop()
        self._update_status_dot()
        self.scan_button.setEnabled(not connected and not connecting and not self._scan_in_progress)
        self.connect_button.setVisible(not connected)
        self.connect_button.setEnabled(not connected and not connecting and has_devices and not self._scan_in_progress)
        self.connect_button.setText(self._tr("device.connect"))
        self.disconnect_button.setVisible(connected)
        self.disconnect_button.setEnabled(connected)
        self.logs_toggle_button.setVisible(connected)
        self.logs_toggle_button.setEnabled(connected)
        self.logs_toggle_button.setText(self._tr("device.show_logs"))
        self.rename_device_button.setVisible(connected)

    def _connection_status_text(self) -> str:
        key = "device.status.connecting" if self._connect_in_progress else "device.status.scanning"
        return f"{self._tr(key).rstrip('.…')}{'.' * self._connection_status_phase}"

    def _tick_connection_status_animation(self) -> None:
        active = (self._connect_in_progress or self._scan_in_progress) and not self._is_connected
        if not active:
            self._connection_status_timer.stop()
            self._sync_connect_buttons()
            return
        self._connection_status_phase = (self._connection_status_phase + 1) % 4
        self.device_status.setText(self._connection_status_text())

    def _ensure_status_pulse(self) -> None:
        if getattr(self, "_status_dot_effect", None) is not None:
            return
        dot = getattr(self, "device_status_dot", None)
        if dot is None:
            return
        self._status_dot_effect = QGraphicsOpacityEffect(dot)
        dot.setGraphicsEffect(self._status_dot_effect)
        self._status_dot_effect.setOpacity(1.0)
        self._status_pulse = QPropertyAnimation(self._status_dot_effect, b"opacity", self)
        self._status_pulse.setDuration(1100)
        self._status_pulse.setLoopCount(-1)
        self._status_pulse.setKeyValueAt(0.0, 1.0)
        self._status_pulse.setKeyValueAt(0.5, 0.4)
        self._status_pulse.setKeyValueAt(1.0, 1.0)
        self._status_pulse.setEasingCurve(QEasingCurve.InOutSine)

    def _update_status_dot(self) -> None:
        """Colour + soft pulse of the sidebar status dot for the current state:
        amber while searching, blue while connecting, steady green when connected.
        """
        dot = getattr(self, "device_status_dot", None)
        if dot is None:
            return
        self._ensure_status_pulse()
        if self._is_connected:
            color = "#46d39a"  # green
        elif self._connect_in_progress:
            color = "#6fa8ff"  # connecting (blue)
        elif self._scan_in_progress:
            color = "#f5b94a"  # searching (amber)
        elif self._reconnecting:
            color = "#ff9a5b"  # reconnecting (orange)
        else:
            color = "rgba(255, 255, 255, 0.30)"  # idle
        dot.setStyleSheet(f"background: {color}; border-radius: {max(2, dot.width() // 2)}px;")
        # _status_pulsing records what the connection state *wants*; whether the
        # animation actually runs is decided by _sync_status_pulse, so a reduced
        # motion session can flip back to full and pick the pulse up again.
        self._status_pulsing = (
            self._connect_in_progress or self._scan_in_progress or self._reconnecting
        ) and not self._is_connected
        self._sync_status_pulse()

    def _sync_status_pulse(self) -> None:
        """Pulse the status dot only while an operation is in flight and motion is
        allowed. Under reduced motion the dot sits at full opacity — its colour
        already carries the state, so nothing is lost.
        """
        pulse = getattr(self, "_status_pulse", None)
        if pulse is None:
            return
        if self._status_pulsing and not motion_policy.reduced:
            if pulse.state() != QAbstractAnimation.Running:
                pulse.start()
            return
        pulse.stop()
        self._status_dot_effect.setOpacity(1.0)

    def _on_motion_changed(self, _reduced: bool) -> None:
        self._sync_status_pulse()

    def _apply_speed(self):
        self._color_ctrl.apply_speed()

    def _queue_selected_effect(self):
        self._color_ctrl.queue_selected_effect()

    def _apply_selected_effect(self):
        self._color_ctrl.apply_selected_effect()

    def _toggle_logs(self):
        self._show_logs_overlay()

    def _show_logs_overlay(self):
        if self._logs_overlay is not None:
            self._logs_overlay.raise_()
            return
        labels = {
            "title": self._tr("logs.title"),
            "subtitle": self._tr("logs.subtitle"),
            "empty": self._tr("logs.empty"),
            "close": self._tr("dialog.ok"),
        }
        overlay = LogsOverlay(labels, self._ui_feedback.localized_log_text(), self)
        self._logs_overlay = overlay
        overlay.closed.connect(lambda: setattr(self, "_logs_overlay", None))
        overlay.open()

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
        self._quick_mode_ctrl.refresh_buttons()

    def _set_active_mode(self, mode_key: str | None, *, update_theme: bool = True):
        self._quick_mode_ctrl.set_active(mode_key, update_theme=update_theme)

    def _current_state_dict(self) -> dict:
        return self._quick_mode_ctrl.current_state()

    def _sync_quick_mode_from_state(self, preferred: str | None = None):
        self._quick_mode_ctrl.sync_from_state(preferred)

    def _note_manual_scene_change(self, *_args) -> None:
        scene_ui = getattr(self, "_scene_ui", None)
        if scene_ui is not None:
            scene_ui.note_manual_light_change()

    def _activate_quick_mode(self, mode_key: str):
        self._quick_mode_ctrl.activate(mode_key)
        self._note_manual_scene_change()

    def _activate_custom_quick_mode(self, index: int) -> None:
        self._quick_mode_ctrl.activate_custom(index)

    def _rename_custom_quick_mode(self, index: int) -> None:
        self._quick_mode_ctrl.rename_custom(index)

    def _finish_rename_custom_quick_mode(self, index: int, name: str) -> None:
        self._quick_mode_ctrl.finish_rename_custom(index, name)

    def _delete_custom_quick_mode(self, index: int) -> None:
        self._quick_mode_ctrl.delete_custom(index)

    def _finish_delete_custom_quick_mode(self, index: int) -> None:
        self._quick_mode_ctrl.finish_delete_custom(index)

    def _save_custom_quick_mode(self) -> None:
        self._quick_mode_ctrl.save_custom()

    def _finish_save_custom_quick_mode(self, name: str) -> None:
        self._quick_mode_ctrl.finish_save_custom(name)

    def _next_custom_quick_key(self) -> str:
        return self._quick_mode_ctrl.next_custom_key()

    def _custom_quick_mode_name(self, mode: dict, index: int) -> str:
        return self._quick_mode_ctrl.custom_name(mode, index)

    def _quick_mode_keys(self) -> set[str]:
        return self._quick_mode_ctrl.keys()

    def _quick_mode_by_key(self, mode_key: str):
        return self._quick_mode_ctrl.by_key(mode_key)

    def _mode_key(self, mode) -> str:
        return self._quick_mode_ctrl.mode_key(mode)

    def _mode_payload(self, mode) -> dict:
        return self._quick_mode_ctrl.payload(mode)

    def _quick_mode_effect_code(self, mode) -> int | None:
        return self._quick_mode_ctrl.effect_code(mode)

    def _quick_mode_matches(self, mode, state: dict) -> bool:
        return self._quick_mode_ctrl.matches(mode, state)

    def _collect_state(self, name):
        return self._quick_mode_ctrl.collect_state(name)

    def _state_to_dict(self, state) -> dict:
        return asdict(state)

    def _can_use(self, feature: str) -> bool:
        return can_use(feature)

    def _persist_settings(self) -> None:
        save_settings(self._settings)

    def _refresh_profiles(self):
        self._profile_controller.refresh_list(self.profile_list)

    def _show_error(self, message):
        self._ble_events.show_error(message)
        self._refresh_diagnostics_view()

    def _log(self, message):
        self._ble_events.log(message)
        self._refresh_diagnostics_view()

    def _diagnostics_text(self) -> str:
        return self._diagnostics_ctrl.text()

    def _refresh_diagnostics_view(self):
        self._diagnostics_ctrl.refresh_view()

    def _copy_diagnostics_report(self):
        self._diagnostics_ctrl.copy_report()

    def _report_unsupported_device(self):
        self._diagnostics_ctrl.report_unsupported()

    def _export_diagnostics_report(self):
        self._diagnostics_ctrl.export_report()

    def _save_window_settings(self):
        self._settings["window_width"] = self.width()
        self._settings["window_height"] = self.height()
        self._settings["language"] = self._language
        self._settings["theme_mode"] = self._theme_mode
        self._settings["theme"] = "dark" if self._is_dark else "light"
        self._settings["capture_compatibility"] = bool(self._settings.get("capture_compatibility", True))
        self._settings["quick_mode"] = self._active_mode_key or ""
        self._settings["custom_quick_modes"] = self._custom_quick_modes
        color_history_limit = PRO_COLOR_HISTORY_COUNT if can_use("color_history_full") else FREE_COLOR_HISTORY_COUNT
        self._settings["color_history"] = self._color_history()[:color_history_limit]
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

    def _start_automations(self) -> None:
        """Hand the automations to their controller.

        Everything about migrating, the engine, the Windows tasks and the journal
        lives behind that one object, so this window — and the automations screen
        after it — has one thing to talk to rather than five.
        """
        self._automations.start()
        # The strip usually connects during the autoconnect that runs well before
        # this, so the engine asks about that itself on start; from here on the edge
        # is delivered as it happens.
        self._ble.connected_changed.connect(
            lambda connected, _address: self._automations.note_connected(connected)
        )
        schedule_first_sync(self._automations)

    def _stop_automations(self) -> None:
        """Stop the engine, once, however many times a close is attempted."""
        self._automation_ui.stop()
        try:
            self._automations.stop()
        except Exception:
            from app.crash_logging import write_current_exception

            write_current_exception(context="automation_runtime_stop")

    def _reflect_automation_state(self, state) -> None:
        """Show what an automation just did, without doing it again.

        Only ever called for a run that confirmed every step. The controls are moved
        with their signals blocked: they are describing the strip, not driving it,
        and letting them emit would send the same colour straight back to the light.
        """
        try:
            blockers = [
                QSignalBlocker(widget)
                for widget in (
                    self.red_slider,
                    self.green_slider,
                    self.blue_slider,
                    self.brightness_slider,
                    self.effect_combo,
                    self.power_button,
                    getattr(self, "speed_slider", None),
                )
                if widget is not None
            ]
            if state.rgb is not None:
                red, green, blue = state.rgb
                self.red_slider.setValue(int(red))
                self.green_slider.setValue(int(green))
                self.blue_slider.setValue(int(blue))
            if state.brightness is not None:
                self.brightness_slider.setValue(int(state.brightness))
            if state.effect is not None:
                index = self.effect_combo.findData(int(state.effect.get("ref", 0)))
                if index >= 0:
                    self.effect_combo.setCurrentIndex(index)
                speed = state.effect.get("speed")
                slider = getattr(self, "speed_slider", None)
                if speed is not None and slider is not None:
                    slider.setValue(int(speed))
            if state.power is not None:
                self.power_button.setChecked(bool(state.power))
            del blockers
            # The handlers that would normally do these never ran.
            self._update_preview()
            self._sync_power_button()
            self._sync_quick_mode_from_state()
        except Exception:
            # A run that already succeeded must not be undone by a display problem.
            from app.crash_logging import write_current_exception

            write_current_exception(context="automation_reflect")

    def _start_deferred(self, delay_ms: int, callback) -> None:
        """Schedule a startup task on a window-owned timer.

        Parented to the window so it's cancelled automatically when the window
        is destroyed, and guarded so it never runs once a close is underway —
        this avoids stray network/UI work firing after the window goes away.
        """
        if _startup_services_disabled():
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._run_deferred(callback))
        timer.start(delay_ms)

    def _run_deferred(self, callback) -> None:
        if self._close_requested:
            return
        callback()

    def _shutdown_tooltip_manager(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._tooltip_manager)
        self._tooltip_manager.shutdown()

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
            self._stop_automations()
            self._tray_controller.hide_icon()
            self._local_api.shutdown()
            self._ambient_ui.shutdown()
            self._music_ui.shutdown()
            self._software_fx_ui.shutdown()
            self._shutdown_tooltip_manager()
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
        # Before the strip is let go: a background automation may be holding the
        # machine-wide execution lock, and a window that went away without releasing
        # it would keep every Windows task from running an automation until the next
        # restart. Done here rather than in the branch above because that one is only
        # reached on the second pass through closeEvent.
        self._stop_automations()
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
    # Single instance: a second launch bows out and surfaces the running window
    # instead, so two copies never fight over the same Bluetooth controller.
    single = SingleInstance()
    if single.is_already_running():
        sys.exit(0)

    # Reduced Motion: install the OS probe and apply the stored mode BEFORE any
    # widgets are built, so a reduced UI never starts an animation at launch.
    _wire_motion_policy(app)

    window = MainWindow()
    single.set_activate_callback(lambda: _surface_window(window))
    # Open at a sane windowed size (restore_startup_size sets ~1320x860 centred)
    # instead of maximised — a maximised window left the content floating in a
    # huge empty area on wide monitors.
    window.show()
    sys.exit(app.exec())


def _wire_motion_policy(app: QApplication) -> None:
    """Install the OS motion probe, apply the stored mode, and re-probe on activation.

    Kept separate from run() so the startup wiring can be exercised in tests
    without spinning up the whole event loop.
    """
    # Provider and stored mode are (re)applied on every call — cheap and always
    # reflects the latest settings.
    motion_policy.set_provider(windows_motion_reduced)
    motion_policy.set_mode(load_settings().get("motion_mode", DEFAULT_MOTION_MODE))
    # The activation signal is connected exactly once per QApplication. run() calls
    # this once, but tests share a single QApplication across cases, so a guard flag
    # keeps repeated calls from stacking duplicate refresh handlers.
    if not app.property("_lumable_motion_wired"):
        # Re-probe the system setting whenever the app becomes active again — this
        # picks up a change to Windows' animation setting without a native filter.
        app.applicationStateChanged.connect(_on_application_state_changed)
        app.setProperty("_lumable_motion_wired", True)


def _on_application_state_changed(state: Qt.ApplicationState) -> None:
    if state == Qt.ApplicationActive:
        motion_policy.refresh()


def _surface_window(window: MainWindow) -> None:
    if window.isMinimized():
        window.showNormal()
    else:
        window.show()
    window.raise_()
    window.activateWindow()

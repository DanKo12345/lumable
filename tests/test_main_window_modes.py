from __future__ import annotations

import warnings

import pytest
from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QApplication, QMenu

from app.app_info import APP_NAME
from app.ble_drivers.base import EffectPreset
from app.feature_gate import FREE_EFFECT_COUNT, invalidate_pro_cache
from app.main_layout import select_section
from app.main_window import MainWindow
from app.quick_modes import QUICK_MODE_MAP, QUICK_MODES


def test_brightness_slider_does_not_auto_activate_quick_mode() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._set_active_mode(None)
        tokens_before = dict(window._theme_tokens)

        window.red_slider.setValue(255)
        window.green_slider.setValue(176)
        window.blue_slider.setValue(98)
        window.brightness_slider.setValue(45)
        window.brightness_slider.setValue(32)

        assert window._active_mode_key is None
        assert window._theme_tokens == tokens_before
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_manual_power_toggle_clears_the_active_scene(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        # Keep the click out of the real BLE stack: set_power would kick off a
        # connect/reconnect loop that the test teardown then waits on forever.
        monkeypatch.setattr(window._ble, "set_power", lambda *_a, **_k: None)
        window._scene_ui._set_active_scene("scene-power")
        window.power_button.click()
        assert window._scene_ui._active_scene_id == ""
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_starting_a_pc_mode_clears_the_active_scene(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        # Disconnected, so the FX toggle raises the "not connected" error —
        # which is a modal dialog that would block the offscreen test forever.
        monkeypatch.setattr(window._ui_feedback, "show_error", lambda *_a, **_k: None)
        window._scene_ui._set_active_scene("scene-fx")
        window.software_fx_toggle.click()
        assert window._scene_ui._active_scene_id == ""
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_edition_badge_shows_free_and_pro(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.hero_signature.edition_label.text() == "Free"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()

    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings, **_kw: True)
    invalidate_pro_cache()
    window = MainWindow()
    try:
        assert window.hero_signature.edition_label.text() == "Pro"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_motion_combo_applies_and_persists_the_selected_mode(monkeypatch, preserve_motion_policy) -> None:
    from app.motion_policy import motion_policy

    saved: dict = {}
    monkeypatch.setattr("app.main_window.save_settings", lambda settings: saved.update(settings))
    motion_policy.set_provider(None)

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        index = window.motion_combo.findData("reduced")
        assert index >= 0
        window.motion_combo.setCurrentIndex(index)

        assert motion_policy.mode == "reduced"
        assert motion_policy.reduced is True
        assert window._settings["motion_mode"] == "reduced"
        assert saved.get("motion_mode") == "reduced"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_startup_wiring_applies_the_stored_motion_mode(monkeypatch, preserve_motion_policy) -> None:
    from app import main_window
    from app.motion_policy import motion_policy

    monkeypatch.setattr(main_window, "load_settings", lambda: {"motion_mode": "reduced"})

    app = QApplication.instance() or QApplication([])
    main_window._wire_motion_policy(app)

    assert motion_policy.mode == "reduced"
    assert motion_policy.reduced is True


def test_application_active_state_refreshes_the_motion_policy(monkeypatch, preserve_motion_policy) -> None:
    from app import main_window
    from app.motion_policy import motion_policy

    monkeypatch.setattr(main_window, "load_settings", lambda: {"motion_mode": "system"})

    app = QApplication.instance() or QApplication([])
    main_window._wire_motion_policy(app)

    # Startup probe says animations are on (not reduced).
    motion_policy.set_provider(lambda: False)
    motion_policy.refresh()
    assert motion_policy.reduced is False

    # The OS setting flips to "reduce animations" while the app is backgrounded;
    # re-activating the window must re-read the provider via the wired signal.
    motion_policy.set_provider(lambda: True)
    app.applicationStateChanged.emit(Qt.ApplicationActive)

    assert motion_policy.reduced is True


def test_repeated_motion_wiring_refreshes_only_once(monkeypatch, preserve_motion_policy) -> None:
    from app import main_window
    from app.motion_policy import motion_policy

    monkeypatch.setattr(main_window, "load_settings", lambda: {"motion_mode": "system"})

    app = QApplication.instance() or QApplication([])
    main_window._wire_motion_policy(app)
    main_window._wire_motion_policy(app)

    calls = {"n": 0}

    def _counting_provider() -> bool:
        calls["n"] += 1
        return False

    motion_policy.set_provider(_counting_provider)
    app.applicationStateChanged.emit(Qt.ApplicationActive)

    assert calls["n"] == 1


def test_status_dot_pulse_stops_at_full_opacity_under_reduced_motion(preserve_motion_policy) -> None:
    from PySide6.QtCore import QAbstractAnimation

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._scan_in_progress = True
        window._update_status_dot()
        assert window._status_pulse.state() == QAbstractAnimation.Running

        policy.set_mode("reduced")
        assert window._status_pulse.state() == QAbstractAnimation.Stopped
        assert window._status_dot_effect.opacity() == 1.0

        # Back to full while the scan is still running: the pulse resumes.
        policy.set_mode("full")
        assert window._status_pulse.state() == QAbstractAnimation.Running

        # ...but once the scan is over it must not come back.
        policy.set_mode("reduced")
        window._scan_in_progress = False
        window._update_status_dot()
        policy.set_mode("full")
        assert window._status_pulse.state() == QAbstractAnimation.Stopped
        assert window._status_dot_effect.opacity() == 1.0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_status_dot_stays_static_when_scan_starts_reduced(preserve_motion_policy) -> None:
    from PySide6.QtCore import QAbstractAnimation

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._scan_in_progress = True
        window._update_status_dot()

        assert window._status_pulsing is True  # the state wants a pulse...
        assert window._status_pulse.state() == QAbstractAnimation.Stopped  # ...motion says no
        assert window._status_dot_effect.opacity() == 1.0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_collected_scene_state_includes_schedule(monkeypatch) -> None:
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings, **_kw: True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.schedule_toggle_button.setChecked(True)
        window.schedule_on_time.setTime(QTime(20, 15))
        window.schedule_off_time.setTime(QTime(23, 45))

        state = window._collect_state("Evening")

        assert state.schedule == {
            "enabled": True,
            "on_time": "20:15",
            "off_time": "23:45",
            "startup_enabled": False,
            "days": [0, 1, 2, 3, 4, 5, 6],
        }
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_loading_scene_restores_schedule_controls(monkeypatch) -> None:
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings, **_kw: True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    profile = {
        "name": "Evening",
        "power": True,
        "brightness": 72,
        "speed": 35,
        "effect_code": 0,
        "color": {"r": 88, "g": 182, "b": 255},
        "schedule": {
            "enabled": True,
            "on_time": "20:15",
            "off_time": "23:45",
            "startup_enabled": False,
        },
    }
    try:
        window._show_error = lambda _message: None
        window._profile_actions.apply_profile_payload(profile)

        assert window.schedule_toggle_button.isChecked()
        assert window.schedule_on_time.time().toString("HH:mm") == "20:15"
        assert window.schedule_off_time.time().toString("HH:mm") == "23:45"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_apply_static_color_uses_single_ble_operation() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []

    class DummyBle:
        def set_static_color(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def set_color_fade(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window._is_connected = True
        window.red_slider.setValue(10)
        window.green_slider.setValue(20)
        window.blue_slider.setValue(30)
        window.brightness_slider.setValue(40)

        window._apply_current_color()

        assert calls == [(10, 20, 30, 40)]
    finally:
        window.close()
        app.processEvents()


def test_apply_static_color_stays_local_when_disconnected() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []

    class DummyBle:
        def set_static_color(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def set_color_fade(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window._is_connected = False
        window.red_slider.setValue(10)

        window._apply_current_color()

        assert calls == []
    finally:
        window.close()
        app.processEvents()


def test_color_sliders_queue_auto_apply_when_connected() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []
    timer_starts = []

    class DummyBle:
        def set_static_color(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def set_color_fade(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    class FakeTimer:
        def start(self) -> None:
            timer_starts.append("start")

        def stop(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window._color_apply_debounce = FakeTimer()
        window._is_connected = True

        window.red_slider.setValue(120)
        window.green_slider.setValue(121)
        window.blue_slider.setValue(122)
        window.brightness_slider.setValue(73)

        assert timer_starts

        window._apply_current_color()

        assert calls == [(120, 121, 122, 73)]
        assert not hasattr(window, "apply_color_button")
    finally:
        window.close()
        app.processEvents()


def test_apply_static_color_updates_aurora_accent() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    class DummyBle:
        def set_static_color(self, *_args) -> None:
            pass

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window.power_button.setChecked(True)
        window.red_slider.setValue(255)
        window.green_slider.setValue(255)
        window.blue_slider.setValue(255)

        window._apply_current_color()

        assert window._aurora._accent_rgb == (255, 255, 255)
        assert window._aurora._accent_enabled is True
    finally:
        window.close()
        app.processEvents()


def test_rainbow_quick_mode_uses_driver_specific_supported_effect() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    class DummyBle:
        def supports_effect_code(self, code: int) -> bool:
            return int(code) == 0x25

        def effect_presets(self):
            return (EffectPreset("static_color", 0), EffectPreset("magic_home_rainbow", 0x25))

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window._is_connected = True

        assert window._quick_mode_effect_code(QUICK_MODE_MAP["rainbow"]) == 0x25
    finally:
        window.close()
        app.processEvents()


def test_connection_actions_show_only_relevant_buttons() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        select_section(window, "settings")  # device controls live on the Settings page
        app.processEvents()
        window._devices = [{"name": "Demo", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-40"}]
        window._scan_in_progress = False
        window._is_connected = False
        window._sync_connect_buttons()

        assert window.connect_button.isVisible()
        assert window.connect_button.isEnabled()
        assert not window.disconnect_button.isVisible()
        assert not window.logs_toggle_button.isVisible()

        window._is_connected = True
        window._sync_connect_buttons()

        assert not window.connect_button.isVisible()
        assert window.disconnect_button.isVisible()
        assert window.logs_toggle_button.isVisible()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_connection_status_animates_while_connecting() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._devices = [{"name": "Demo", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-40"}]
        window._scan_in_progress = False
        window._is_connected = False
        window._connect_in_progress = True
        window._sync_connect_buttons()

        assert window.device_status.text() == window._tr("device.status.connecting").rstrip(".")
        assert window.connect_button.text() == window._tr("device.connect")
        assert window._connection_status_timer.isActive()

        window._tick_connection_status_animation()
        assert window.device_status.text() == f"{window._tr('device.status.connecting').rstrip('.')}."
        assert window.connect_button.text() == window._tr("device.connect")

        window._connect_in_progress = False
        window._sync_connect_buttons()

        assert not window._connection_status_timer.isActive()
        assert window.connect_button.text() == window._tr("device.connect")
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_rgb_slider_preview_updates_immediately() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        calls = []
        window.preview.set_color = lambda color: calls.append(color)

        new_value = 124 if window.red_slider.value() == 123 else 123
        window.red_slider.setValue(new_value)

        assert calls[-1].red() == new_value
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_rgb_slider_does_not_send_ble_when_disconnected() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []

    class DummyBle:
        def set_static_color(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def set_color_fade(self, red: int, green: int, blue: int, brightness: int) -> None:
            calls.append((red, green, blue, brightness))

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window._is_connected = False

        new_value = 124 if window.red_slider.value() == 123 else 123
        window.red_slider.setValue(new_value)

        assert calls == []
        assert window._local_color_debounce.isActive()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_connection_refreshes_power_button_action_text(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    monkeypatch.setattr("app.ble_event_handler.save_settings", lambda _settings: None)
    window = MainWindow()
    try:
        window.power_button.setChecked(True)
        window.power_button.setText(window._tr("color.power_on"))

        window._ble_events.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")

        assert window.power_button.text() == window._tr("color.power_off")
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_tray_notice_is_shown_once() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    class FakeTrayIcon:
        def __init__(self) -> None:
            self.messages = []

        def isVisible(self) -> bool:
            return True

        def showMessage(self, title, message, icon, timeout) -> None:
            self.messages.append((title, message, icon, timeout))

        def hide(self) -> None:
            pass

    try:
        fake_tray = FakeTrayIcon()
        window._tray_controller._icon = fake_tray

        window._tray_controller.show_notice_once()
        window._tray_controller.show_notice_once()

        assert len(fake_tray.messages) == 1
        title, message, _icon, timeout = fake_tray.messages[0]
        assert title == APP_NAME
        assert message == window._tr("tray.notice")
        assert timeout == 3000
        assert window._tray_controller._notice_shown is True
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_tray_quick_controls_show_locked_state_in_free(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        monkeypatch.setattr("app.tray_controller.can_use", lambda feature: False if feature == "tray_quick_controls" else True)
        window._tray_controller._quick_menu = QMenu(window)
        window._tray_controller.rebuild_quick_menu()
        menu = window._tray_controller._quick_menu

        assert menu is not None
        assert [action.text() for action in menu.actions()] == [
            window._tr("tray.quick_locked"),
            window._tr("tray.unlock_pro"),
        ]
        assert menu.actions()[0].isEnabled() is False
        assert menu.actions()[1].isEnabled() is True
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_tray_quick_controls_show_pro_actions(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        monkeypatch.setattr("app.tray_controller.can_use", lambda _feature: True)
        window._tray_controller._quick_menu = QMenu(window)
        window._settings["color_history"] = [{"r": 255, "g": 0, "b": 0}]
        window._tray_controller.rebuild_quick_menu()
        menu = window._tray_controller._quick_menu

        assert menu is not None
        texts = [action.text() for action in menu.actions()]
        assert window._tr("color.power_off") in texts
        assert window._tr("tray.brightness") in texts
        assert window._tr("tray.recent_colors") in texts
        assert window._tr("tray.profiles") in texts
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_power_button_uses_action_label_and_role_for_state() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.power_button.setChecked(False)
        window._sync_power_button()

        assert window.power_button.text() == window._tr("color.power_on")
        # Off → neutral glass; on → tinted with the current LED colour.
        assert window.power_button._role == "ghost"

        window.power_button.setChecked(True)
        window._sync_power_button()

        assert window.power_button.text() == window._tr("color.power_off")
        assert window.power_button._role == "led"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_keyboard_shortcuts_are_registered_for_power_and_quick_modes() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert len(window._shortcuts) == 1 + min(5, len(QUICK_MODES))
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_power_shortcut_toggles_power_when_focus_is_not_text_input() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls: list[bool] = []

    class DummyBle:
        def set_power(self, enabled: bool) -> None:
            calls.append(enabled)

        def supports_effect_code(self, _code: int) -> bool:
            return True

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window.power_button.setChecked(False)

        window._handle_power_shortcut()

        assert window.power_button.isChecked()
        assert calls == [True]
    finally:
        window.close()
        app.processEvents()


def test_power_off_clears_aurora_accent() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls: list[bool] = []

    class DummyBle:
        def set_power(self, enabled: bool) -> None:
            calls.append(enabled)

        def supports_effect_code(self, _code: int) -> bool:
            return True

        def supports_effect_speed(self) -> bool:
            return True

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window._aurora.set_accent_color(255, 255, 255)
        window.power_button.setChecked(False)

        window._toggle_power()

        assert calls == [False]
        assert window._aurora._accent_enabled is False
    finally:
        window.close()
        app.processEvents()


def test_shortcuts_do_not_fire_while_text_input_has_focus() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls: list[str] = []
    try:
        window.show()
        window.activateWindow()
        # Force focus to land even when the suite runs behind another window.
        # setActiveWindow is deprecated in Qt6 but still the only reliable way to
        # do this headless; the warning is irrelevant to what we're testing.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            QApplication.setActiveWindow(window)
        select_section(window, "profiles")  # profile name input lives on the Profiles page
        app.processEvents()
        window.profile_name.setFocus()
        app.processEvents()
        if QApplication.focusWidget() is not window.profile_name:
            pytest.skip("window could not take keyboard focus in this environment")
        window._activate_quick_mode = lambda mode_key: calls.append(mode_key)

        window._handle_quick_mode_shortcut("gaming")

        assert calls == []
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_brightness_slider_uses_white_accent() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.brightness_slider.accent == "white"
        window._theme_controller.apply_slider_theme()
        assert window.brightness_slider.accent == "white"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_slider_value_chips_are_interactive() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        chips = [
            window.red_value,
            window.green_value,
            window.blue_value,
            window.brightness_value,
            window.speed_value,
        ]

        for chip in chips:
            assert chip.cursor().shape() == Qt.PointingHandCursor
            assert chip.focusPolicy() == Qt.StrongFocus
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_static_color_hides_speed_controls() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()

        index = window.effect_combo.findData(0)
        window.effect_combo.setCurrentIndex(index)
        window._sync_effect_preview()
        app.processEvents()

        assert not window.speed_slider.isVisible()
        assert not window.speed_value.isVisible()
        assert not window._slider_labels["effects.speed"].isVisible()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_non_static_effect_shows_speed_controls() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        select_section(window, "effects")  # speed controls live on the Effects page
        app.processEvents()

        for index in range(window.effect_combo.count()):
            if int(window.effect_combo.itemData(index) or 0) != 0:
                window.effect_combo.setCurrentIndex(index)
                break
        window._sync_effect_preview()
        app.processEvents()

        assert window.speed_slider.isVisible()
        assert window.speed_value.isVisible()
        assert window._slider_labels["effects.speed"].isVisible()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_quick_mode_updates_aurora_accent_immediately() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    class DummyBle:
        def set_static_color(self, *_args) -> None:
            pass

        def set_power(self, *_args) -> None:
            pass

        def supports_effect_code(self, _code: int) -> bool:
            return True

        def supports_effect_speed(self) -> bool:
            return True

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        mode = QUICK_MODE_MAP["gaming"]
        applied_payloads = []
        window._profile_actions.apply_profile_payload = (
            lambda payload, announce_load=False: applied_payloads.append((payload, announce_load))
        )

        window._activate_quick_mode("gaming")

        assert applied_payloads
        assert window._aurora._accent_rgb == tuple(mode.color)
        assert window._aurora._accent_enabled is True
    finally:
        window.close()
        app.processEvents()


def test_custom_quick_mode_pins_selected_profile(monkeypatch) -> None:
    monkeypatch.setattr("app.main_window.can_use", lambda feature: True)
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        profile = {
            "name": "Desk Config",
            "power": True,
            "brightness": 78,
            "speed": 45,
            "effect_code": 0,
            "color": {"r": 12, "g": 34, "b": 56},
            "schedule": {"enabled": True, "on_time": "19:30", "off_time": "23:15", "startup_enabled": False},
        }
        window._profiles[:] = [profile]
        window._refresh_profiles()
        window.profile_list.setCurrentRow(0)
        window._custom_quick_modes = []
        window._settings["custom_quick_modes"] = []
        window._refresh_quick_mode_buttons()

        window._save_custom_quick_mode()

        assert len(window._custom_quick_modes) == 1
        mode = window._custom_quick_modes[0]
        assert mode["name"] == "Desk Config"
        assert mode["source_profile_name"] == "Desk Config"
        assert mode["color"] == {"r": 12, "g": 34, "b": 56}
        assert mode["brightness"] == 78
        assert mode["speed"] == 45
        assert mode["schedule"]["on_time"] == "19:30"
        assert mode["schedule"]["off_time"] == "23:15"
        assert window._custom_mode_buttons[0].isHidden() is False
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_custom_quick_mode_activation_applies_payload(monkeypatch) -> None:
    monkeypatch.setattr("app.main_window.can_use", lambda feature: True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    payloads = []
    try:
        window._custom_quick_modes = [
            {
                "key": "custom_1",
                "name": "Desk Scene",
                "power": True,
                "brightness": 64,
                "speed": 40,
                "effect_code": 0,
                "color": {"r": 20, "g": 40, "b": 60},
                "schedule": {"enabled": True, "on_time": "19:00", "off_time": "23:00", "startup_enabled": False},
                "accent": "#14283c",
            }
        ]
        window._profile_actions.apply_profile_payload = lambda payload, announce_load=False: payloads.append(payload)

        window._activate_custom_quick_mode(0)

        assert window._active_mode_key == "custom_1"
        assert payloads[0]["name"] == "Desk Scene"
        assert payloads[0]["schedule"]["enabled"] is True
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_legacy_desk_scene_name_is_displayed_as_localized_scene(monkeypatch) -> None:
    monkeypatch.setattr("app.main_window.can_use", lambda feature: True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._custom_quick_modes = [
            {
                "key": "custom_1",
                "name": "Desk Scene",
                "power": True,
                "brightness": 64,
                "speed": 40,
                "effect_code": 0,
                "color": {"r": 20, "g": 40, "b": 60},
                "schedule": {"enabled": False, "on_time": "19:00", "off_time": "23:00", "startup_enabled": False},
                "accent": "#14283c",
            }
        ]

        window._refresh_quick_mode_buttons()

        assert window._custom_mode_buttons[0].text() == window._tr("mode.custom_default", number=1)
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_custom_quick_mode_uses_current_profile_payload(monkeypatch) -> None:
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._profiles[:] = [
            {
                "name": "Movie",
                "power": True,
                "brightness": 91,
                "speed": 40,
                "effect_code": 0,
                "color": {"r": 80, "g": 90, "b": 100},
                "schedule": {"enabled": False, "on_time": "19:00", "off_time": "23:00", "startup_enabled": False},
            }
        ]
        window._custom_quick_modes = [
            {
                "key": "custom_1",
                "name": "Movie",
                "source_profile_name": "Movie",
                "power": True,
                "brightness": 64,
                "speed": 40,
                "effect_code": 0,
                "color": {"r": 20, "g": 40, "b": 60},
                "schedule": {"enabled": False, "on_time": "19:00", "off_time": "23:00", "startup_enabled": False},
                "accent": "#14283c",
            }
        ]

        payload = window._mode_payload(window._custom_quick_modes[0])

        assert payload["brightness"] == 91
        assert payload["color"] == {"r": 80, "g": 90, "b": 100}
        window._refresh_quick_mode_buttons()
        assert window._custom_mode_buttons[0].text() == "Movie"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_custom_quick_mode_delete_clears_active_mode(monkeypatch) -> None:
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._custom_quick_modes = [
            {
                "key": "custom_1",
                "name": "Movie",
                "power": True,
                "brightness": 64,
                "speed": 40,
                "effect_code": 0,
                "color": {"r": 20, "g": 40, "b": 60},
                "schedule": {"enabled": False, "on_time": "19:00", "off_time": "23:00", "startup_enabled": False},
                "accent": "#14283c",
            }
        ]
        window._active_mode_key = "custom_1"
        window._settings["quick_mode"] = "custom_1"

        window._finish_delete_custom_quick_mode(0)

        assert window._custom_quick_modes == []
        assert window._settings["custom_quick_modes"] == []
        assert window._active_mode_key is None
        assert window._settings["quick_mode"] == ""
        assert window._custom_mode_buttons[0].isHidden() is True
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_free_mode_locks_effects_after_free_limit(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.effect_combo.count() > FREE_EFFECT_COUNT
        for index in range(FREE_EFFECT_COUNT):
            assert window.effect_combo.itemData(index) is not None
        # Locked effects are marked by a None payload and a dimmed lock swatch
        # icon (the old "🔒 " text prefix was replaced by the swatch design).
        assert window.effect_combo.itemData(FREE_EFFECT_COUNT) is None
        assert not window.effect_combo.itemText(FREE_EFFECT_COUNT).startswith("🔒")
        assert not window.effect_combo.itemIcon(FREE_EFFECT_COUNT).isNull()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_free_mode_blocks_locked_effect_selection(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []
    try:
        window._show_license_overlay = lambda: calls.append("license")
        window.effect_combo.setCurrentIndex(FREE_EFFECT_COUNT)
        window._queue_selected_effect()

        assert calls == ["license"]
        assert window.effect_combo.currentData() == 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_free_mode_limits_visible_color_history(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        window._settings["color_history"] = [
            {"r": index, "g": index + 1, "b": index + 2}
            for index in range(6)
        ]
        window._refresh_color_history()

        assert sum(button.isVisible() for button in window.color_history_buttons) == 6
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_free_mode_blocks_schedule_toggle(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []
    try:
        window._show_license_overlay = lambda: calls.append("license")
        window.schedule_toggle_button.setChecked(True)
        window._toggle_schedule()

        assert calls == ["license"]
        assert not window.schedule_toggle_button.isChecked()
        assert window._settings["schedule"]["enabled"] is False
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_free_mode_blocks_profile_import_export(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []
    try:
        window._show_license_overlay = lambda: calls.append("license")

        window._profile_actions.import_profiles()
        window._profile_actions.export_profiles()

        assert calls == ["license", "license"]
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_layout_stays_constrained_on_large_desktop_resolutions() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        for width, height in ((1920, 1080), (2560, 1440), (3840, 2160)):
            window.resize(width, height)
            window.show()
            app.processEvents()

            # Content is width-capped (app shell), not stretched edge to edge.
            select_section(window, "settings")
            app.processEvents()
            assert window._section_stack.width() <= window._sz(1120) + 8
            assert window.body_scroll.width() <= window.width()
            assert window.device_card.width() > 0
            assert window.diagnostics_card.width() > 0

            select_section(window, "profiles")
            app.processEvents()
            assert window.configs_card.width() > 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()

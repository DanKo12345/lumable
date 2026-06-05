from __future__ import annotations

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import QApplication

from app.app_info import APP_NAME
from app.ble_drivers.base import EffectPreset
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


def test_edition_badge_shows_free_and_pro(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.hero_signature.edition_label.text() == "Free"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()

    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings: True)
    window = MainWindow()
    try:
        assert window.hero_signature.edition_label.text() == "Pro"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_collected_scene_state_includes_schedule(monkeypatch) -> None:
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings: True)
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
        }
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_loading_scene_restores_schedule_controls(monkeypatch) -> None:
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings: True)
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

        def shutdown(self) -> None:
            pass

        def shutdown_async(self) -> None:
            pass

    try:
        window._ble.shutdown()
        window._ble = DummyBle()
        window.red_slider.setValue(10)
        window.green_slider.setValue(20)
        window.blue_slider.setValue(30)
        window.brightness_slider.setValue(40)

        window._apply_current_color()

        assert calls == [(10, 20, 30, 40)]
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

        assert window._aurora._accent.red() == 255
        assert window._aurora._accent.green() == 255
        assert window._aurora._accent.blue() == 255
        assert window._aurora._accent.alpha() == 38
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


def test_connect_button_animates_while_connecting() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._devices = [{"name": "Demo", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-40"}]
        window._scan_in_progress = False
        window._is_connected = False
        window._connect_in_progress = True
        window._sync_connect_buttons()

        assert window.connect_button.text() == window._tr("device.connecting").rstrip(".")
        assert window._connect_button_timer.isActive()

        window._tick_connect_button_animation()
        assert window.connect_button.text() == f"{window._tr('device.connecting').rstrip('.')}."

        window._connect_in_progress = False
        window._sync_connect_buttons()

        assert not window._connect_button_timer.isActive()
        assert window.connect_button.text() == window._tr("device.connect")
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


def test_power_button_uses_action_label_and_role_for_state() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.power_button.setChecked(False)
        window._sync_power_button()

        assert window.power_button.text() == window._tr("color.power_on")
        assert window.power_button._role == "ghost"

        window.power_button.setChecked(True)
        window._sync_power_button()

        assert window.power_button.text() == window._tr("color.power_off")
        assert window.power_button._role == "accent_soft"
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
        assert window._aurora._accent.alpha() == 0
    finally:
        window.close()
        app.processEvents()


def test_shortcuts_do_not_fire_while_text_input_has_focus() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls: list[str] = []
    try:
        window.show()
        window.profile_name.setFocus()
        app.processEvents()
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
        assert (
            window._aurora._accent.red(),
            window._aurora._accent.green(),
            window._aurora._accent.blue(),
            window._aurora._accent.alpha(),
        ) == (*mode.color, 38)
    finally:
        window.close()
        app.processEvents()


def test_free_mode_locks_effects_after_free_limit(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.effect_combo.count() > 5
        for index in range(5):
            assert window.effect_combo.itemData(index) is not None
        assert window.effect_combo.itemData(5) is None
        assert window.effect_combo.itemText(5).startswith("🔒 ")
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
        window.effect_combo.setCurrentIndex(5)
        window._queue_selected_effect()

        assert calls == ["license"]
        assert window.effect_combo.currentData() == 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_free_mode_blocks_hsv_color_picker(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []
    try:
        window._show_license_overlay = lambda: calls.append("license")
        window._pick_color()

        assert calls == ["license"]
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

        assert sum(button.isVisible() for button in window.color_history_buttons) == 3
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

            assert window.content_shell.width() <= 2360
            assert window.content_shell.x() >= 0
            assert window.body_scroll.width() <= window.content_shell.width()
            assert window.device_card.width() > 0
            assert window.configs_card.width() > 0
            assert window.diagnostics_card.width() > 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()

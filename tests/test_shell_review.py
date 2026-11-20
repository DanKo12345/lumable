from __future__ import annotations

from itertools import pairwise
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.main_layout import select_section
from app.main_window import MainWindow
from tools.shoot_screen import DEMOS


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        yield win
    finally:
        win._ble.shutdown()
        win.close()
        app.processEvents()


def test_rebuilt_rule_buttons_leave_the_theme_registry(window, monkeypatch):
    monkeypatch.setenv("LUMABLE_FORCE_PRO", "1")
    DEMOS["automations"](window)
    old_buttons = list(window._buttons)
    assert len(window._automation_ui._rows) == 5

    window._automation_ui.sync_controls()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert any(not isValid(button) for button in old_buttons)
    assert all(isValid(button) for button in window._buttons)
    window._theme_controller.toggle_theme()


def test_dropdown_can_confirm_and_cancel_from_the_keyboard(window):
    window.show()
    select_section(window, "effects")
    combo = window.effect_combo
    combo.setCurrentIndex(0)
    window.activateWindow()
    QApplication.processEvents()
    combo.setFocus()
    combo.showPopup()
    QTest.keyClick(combo._list, Qt.Key.Key_Down)
    QTest.keyClick(combo._list, Qt.Key.Key_Return)
    assert combo.currentIndex() == 1
    assert not combo._popup.isVisible()
    assert window.focusWidget() is combo

    combo.showPopup()
    QTest.keyClick(combo._list, Qt.Key.Key_Down)
    QTest.keyClick(combo._list, Qt.Key.Key_Escape)
    assert combo.currentIndex() == 1
    assert not combo._popup.isVisible()
    assert window.focusWidget() is combo


def test_narrow_quick_mode_row_keeps_all_shortcuts_reachable(window, monkeypatch):
    names = ("Work at the computer", "Quiet evening", "Bright desk", "Window lights")
    window._custom_quick_modes = [
        {"key": f"review_{index}", "name": name, "effect_code": 0} for index, name in enumerate(names)
    ]
    window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    window.show()
    QApplication.processEvents()
    window._refresh_quick_mode_buttons()
    row = window.quick_modes_row
    row_buttons = [
        *window._mode_buttons.values(), *window._custom_mode_buttons, row.more_button, window.save_quick_mode_button,
    ]
    visible = sorted((button for button in row_buttons if button.isVisible()), key=lambda button: button.x())
    assert row.more_button.isVisible()
    assert all(row.rect().contains(button.geometry()) for button in visible)
    assert all(a.geometry().right() < b.geometry().left() for a, b in pairwise(visible))

    monkeypatch.setattr(row.menu, "popup", Mock())
    activate = Mock()
    remove = Mock()
    monkeypatch.setattr(window, "_activate_custom_quick_mode", activate)
    monkeypatch.setattr(window, "_delete_custom_quick_mode", remove)
    row.show_more()
    hidden_names = [name for name, button in zip(names, window._custom_mode_buttons, strict=True) if button.isHidden()]
    assert hidden_names
    actions = {action.text(): action for action in row.menu.actions() if not action.isSeparator()}
    assert all(name in actions for name in hidden_names)
    actions[hidden_names[-1]].trigger()
    activate.assert_called_once_with(names.index(hidden_names[-1]))
    actions[window._tr("mode.remove_shortcut")].menu().actions()[-1].trigger()
    remove.assert_called_once_with(names.index(hidden_names[-1]))

    window.resize(1630, 880)
    QApplication.processEvents()
    assert sum(not button.isHidden() for button in window._custom_mode_buttons) > len(names) - len(hidden_names)
    window._custom_quick_modes = [{"key": "desk", "name": "Desk", "effect_code": 0}]
    window._refresh_quick_mode_buttons()
    assert not window._custom_mode_buttons[0].isHidden()
    assert all(button.isHidden() for button in window._custom_mode_buttons[1:])
    assert row.more_button.isHidden()


def test_first_run_header_searches_instead_of_writing_power(window, monkeypatch):
    scan = Mock()
    power = Mock()
    monkeypatch.setattr(window._ble, "scan", scan)
    monkeypatch.setattr(window._ble, "set_power", power)
    desired = window.power_button.isChecked()
    assert window.power_button.text() == window._tr("device.find_strip")
    hint = window._tr("device.preview_hint")
    assert window.device_status_hint.text() == hint
    assert hint in window.device_status_card.toolTip()
    assert window.preview.swatch.layout() is None

    window.power_button.click()
    scan.assert_called_once_with()
    power.assert_not_called()
    assert window._section_stack.currentWidget() is window._nav_pages["settings"]
    assert window.power_button.isChecked() == desired
    assert not window.power_button.isEnabled()

    window._scan_in_progress = False
    window._ble_events.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")
    assert window.device_status_hint.text() != hint
    assert hint not in window.device_status_card.toolTip()
    assert window.power_button.isEnabled()
    assert window.power_button.text() == window._tr("color.power_off" if desired else "color.power_on")


def test_preview_density_and_navigation_follow_the_task(window):
    window.resize(1280, 820)
    window.show()
    select_section(window, "color")
    assert not window.preview._compact
    for page in ("effects", "ambient", "music", "schedule", "automations"):
        select_section(window, page)
        assert window.preview._compact

    select_section(window, "color")
    window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    QApplication.processEvents()
    assert window.preview._compact
    assert window._nav_pages["schedule"].isAncestorOf(window.timers_card)
    assert window._nav_pages["automations"].isAncestorOf(window.app_triggers_card)

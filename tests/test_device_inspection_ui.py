"""What the device card offers for a controller nobody recognises.

The rule the tests protect: an unrecognised device is never offered an ordinary
connection, because that means writing a guessed protocol to unknown hardware.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.scan_snapshot import GattCharacteristic, GattInspection, GattService


@pytest.fixture()
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        yield win
    finally:
        win._ble.shutdown()
        win.close()
        app.processEvents()


def _offer(window, *devices) -> None:
    window._devices = list(devices)
    window.device_combo.clear()
    for device in devices:
        window.device_combo.addItem(device["name"])
    window.device_combo.setCurrentIndex(0)
    QApplication.instance().processEvents()


def _supported(name="ELK-BLEDOM"):
    return {"name": name, "address": "AA:BB:CC:DD:EE:01", "supported": True}


def _unknown(name="SP630E"):
    return {"name": name, "address": "AA:BB:CC:DD:EE:02", "supported": False}


def test_a_supported_strip_still_offers_an_ordinary_connection(window) -> None:
    _offer(window, _supported())
    window._sync_connect_buttons()

    assert window.connect_button.text() == window._tr("device.connect")


def test_an_unrecognised_device_is_offered_a_check_instead(window) -> None:
    _offer(window, _unknown())
    window._sync_connect_buttons()

    assert window.connect_button.text() == window._tr("device.inspect")


def test_choosing_the_other_device_swaps_the_button(window) -> None:
    _offer(window, _supported(), _unknown())
    window._sync_connect_buttons()
    assert window.connect_button.text() == window._tr("device.connect")

    window.device_combo.setCurrentIndex(1)
    QApplication.instance().processEvents()

    assert window.connect_button.text() == window._tr("device.inspect")


def test_pressing_it_starts_a_check_and_never_a_connection(window, monkeypatch) -> None:
    connects: list = []
    inspects: list = []
    monkeypatch.setattr(window._ble, "connect_to_address", lambda address: connects.append(address))
    monkeypatch.setattr(
        window._ble, "inspect_device", lambda address, name="", token=0: inspects.append(address)
    )
    _offer(window, _unknown())

    window._ble_events.handle_connect()

    assert connects == [], "an unrecognised device was sent down the connect path"
    assert inspects == ["AA:BB:CC:DD:EE:02"]
    assert window._inspect_in_progress is True


def test_a_running_check_blocks_scanning_connecting_and_itself(window, monkeypatch) -> None:
    errors: list = []
    monkeypatch.setattr(window._ble_events, "show_error", lambda message: errors.append(message))
    monkeypatch.setattr(window._ble, "inspect_device", lambda *a, **k: None)
    _offer(window, _unknown())
    window._ble_events.handle_connect()
    errors.clear()

    window._sync_connect_buttons()
    assert window.connect_button.isEnabled() is False
    assert window.scan_button.isEnabled() is False
    assert window.connect_button.text() == window._tr("device.inspect_running")

    window._ble_events.handle_connect()
    window._ble_events.start_scan()
    assert errors == [window._tr("error.wait_inspect")] * 2


def test_a_finished_check_reports_what_it_found(window) -> None:
    _offer(window, _unknown())
    window._inspect_in_progress = True
    window._inspection_token = 7
    inspection = GattInspection(
        address="AA:BB",
        name="SP630E",
        token=7,
        services=(
            GattService("0000fff0", (GattCharacteristic("0000fff3", ("write",)),)),
            GattService("0000180a", ()),
        ),
    )

    window._on_inspection_finished(inspection)

    assert window._inspect_in_progress is False
    assert window.connect_button.isEnabled() is True


def test_a_failed_check_explains_itself_without_a_traceback(window, monkeypatch) -> None:
    shown: list = []
    monkeypatch.setattr(window, "_show_error", lambda message: shown.append(message))
    window._inspect_in_progress = True
    window._inspection_token = 3

    window._on_inspection_finished(
        GattInspection(address="AA:BB", token=3, error="BleakError: [WinError -2147] whatever")
    )

    assert shown == [window._tr("device.inspect_failed")]
    assert "WinError" not in shown[0]
    assert window._inspect_in_progress is False


def test_a_result_overtaken_by_a_rescan_is_ignored(window, monkeypatch) -> None:
    """The device list it was about is gone; acting on it would report a check
    of something the user is no longer looking at."""
    shown: list = []
    monkeypatch.setattr(window, "_show_error", lambda message: shown.append(message))
    window._inspect_in_progress = True
    window._inspection_token = 5

    window._inspection_token += 1  # a rescan happened
    window._on_inspection_finished(GattInspection(address="AA:BB", token=5, error="too late"))

    assert shown == []


def test_closing_the_window_abandons_a_running_check(window) -> None:
    window._inspect_in_progress = True
    before = window._inspection_token

    window._abandon_inspection()

    assert window._inspect_in_progress is False
    assert window._inspection_token != before


def test_the_check_button_is_reachable_and_named_for_assistive_tools(window) -> None:
    """It replaces Connect in place, so it inherits its keyboard reachability —
    but the announced name must change with the label, not stay "Connect"."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAccessible

    _offer(window, _unknown())
    window._sync_connect_buttons()
    window.show()

    button = window.connect_button
    assert button.focusPolicy() != Qt.NoFocus
    interface = QAccessible.queryAccessibleInterface(button)
    assert interface is not None
    # The visible label is shortened to fit the card; the announced name is the
    # full phrase, because that is what has to make sense read aloud.
    assert interface.text(QAccessible.Text.Name) == window._tr("device.inspect_full")
    assert button.toolTip() == window._tr("device.inspect_hint")


def test_the_check_can_be_started_from_the_keyboard(window, monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    inspects: list = []
    monkeypatch.setattr(
        window._ble, "inspect_device", lambda address, name="", token=0: inspects.append(address)
    )
    _offer(window, _unknown())
    window._sync_connect_buttons()
    window.show()
    window.connect_button.setFocus()

    QTest.keyClick(window.connect_button, Qt.Key_Space)

    assert inspects == ["AA:BB:CC:DD:EE:02"]


def test_the_busy_label_does_not_animate_under_reduced_motion(window, preserve_motion_policy) -> None:
    """The running state is a static label, not a ticking one — nothing here is
    driven by a timer that reduced motion would have to stop."""
    _offer(window, _unknown())
    window._inspect_in_progress = True
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("reduced")

    window._sync_connect_buttons()
    first = window.connect_button.text()
    window._sync_connect_buttons()

    assert first == window.connect_button.text() == window._tr("device.inspect_running")


def test_the_button_still_fits_the_minimum_window(window) -> None:
    from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH

    _offer(window, _unknown())
    window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    window.show()
    window._sync_connect_buttons()
    QApplication.instance().processEvents()

    button = window.connect_button
    # The longer label must not be clipped: the hint width has to cover it.
    assert button.width() >= button.fontMetrics().horizontalAdvance(button.text())

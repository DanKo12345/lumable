from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app import ble_event_handler
from app.ble_event_handler import BleEventHandler


class FakeCombo:
    def __init__(self) -> None:
        self.items: list[tuple[str, Any]] = []
        self.index = -1

    def clear(self) -> None:
        self.items.clear()
        self.index = -1

    def addItem(self, text: str, data: Any = None) -> None:
        self.items.append((text, data))
        if self.index == -1:
            self.index = 0

    def currentIndex(self) -> int:
        return self.index

    def setCurrentIndex(self, index: int) -> None:
        self.index = index

    def findData(self, data: Any) -> int:
        for index, item in enumerate(self.items):
            if item[1] == data:
                return index
        return -1


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""
        self.visible = True

    def setText(self, text: str) -> None:
        self.text = text

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


class FakeButton:
    def __init__(self) -> None:
        self.enabled = True
        self.visible = True
        self.text = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setVisible(self, visible: bool) -> None:
        self.visible = visible

    def setText(self, text: str) -> None:
        self.text = text


class FakeBle:
    def __init__(self) -> None:
        self.scan_called = False
        self.connected_to: list[str] = []

    def scan(self) -> None:
        self.scan_called = True

    def connect_to_address(self, address: str) -> None:
        self.connected_to.append(address)


class FakeFeedback:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.logs: list[str] = []

    def show_error(self, message: str) -> None:
        self.errors.append(message)

    def log(self, message: str) -> None:
        self.logs.append(message)


@dataclass
class FakeHost:
    _ble: FakeBle = field(default_factory=FakeBle)
    _devices: list[dict[str, Any]] = field(default_factory=list)
    _is_connected: bool = False
    _scan_in_progress: bool = False
    _connect_in_progress: bool = False
    _settings: dict[str, Any] = field(default_factory=dict)
    _ui_feedback: FakeFeedback = field(default_factory=FakeFeedback)

    device_combo: FakeCombo = field(default_factory=FakeCombo)
    device_status: FakeLabel = field(default_factory=FakeLabel)
    last_device_label: FakeLabel = field(default_factory=FakeLabel)
    device_onboarding_label: FakeLabel = field(default_factory=FakeLabel)
    scan_button: FakeButton = field(default_factory=FakeButton)
    connect_button: FakeButton = field(default_factory=FakeButton)
    disconnect_button: FakeButton = field(default_factory=FakeButton)
    logs_toggle_button: FakeButton = field(default_factory=FakeButton)
    quick_refresh_count: int = 0
    effect_refresh_count: int = 0

    def _tr(self, key: str, **kwargs: object) -> str:
        if kwargs:
            args = ",".join(f"{name}={value}" for name, value in kwargs.items())
            return f"{key}:{args}"
        return key

    def _refresh_quick_mode_buttons(self) -> None:
        self.quick_refresh_count += 1

    def _refresh_effect_names(self) -> None:
        self.effect_refresh_count += 1

    def _sync_connect_buttons(self) -> None:
        connected = bool(self._is_connected)
        connecting = bool(self._connect_in_progress)
        has_devices = bool(self._devices)
        self.scan_button.setEnabled(not connected and not connecting and not self._scan_in_progress)
        self.connect_button.setVisible(not connected)
        self.connect_button.setEnabled(not connected and not connecting and has_devices and not self._scan_in_progress)
        self.connect_button.setText(self._tr("device.connecting") if connecting else self._tr("device.connect"))
        self.disconnect_button.setVisible(connected)
        self.disconnect_button.setEnabled(connected)
        self.logs_toggle_button.setVisible(connected)
        self.logs_toggle_button.setEnabled(connected)


def test_start_scan_resets_ui_and_calls_ble_scan() -> None:
    host = FakeHost(_devices=[{"address": "old"}])
    handler = BleEventHandler(host)

    handler.start_scan()

    assert host._scan_in_progress is True
    assert host._devices == []
    assert host.device_combo.items == [("device.choice.scan_placeholder", None)]
    assert host.device_status.text == "device.status.scanning"
    assert host.device_onboarding_label.visible is False
    assert host.connect_button.enabled is False
    assert host.connect_button.visible is True
    assert host.disconnect_button.enabled is False
    assert host.disconnect_button.visible is False
    assert host._ble.scan_called is True


def test_start_scan_blocks_while_connected_or_connecting() -> None:
    connected_host = FakeHost(_is_connected=True)
    BleEventHandler(connected_host).start_scan()
    assert connected_host._ui_feedback.errors == ["error.disconnect_before_scan"]
    assert connected_host._ble.scan_called is False

    connecting_host = FakeHost(_connect_in_progress=True)
    BleEventHandler(connecting_host).start_scan()
    assert connecting_host._ui_feedback.errors == ["error.wait_connect"]
    assert connecting_host._ble.scan_called is False


def test_handle_connect_blocks_while_scan_is_running() -> None:
    host = FakeHost(_scan_in_progress=True)
    handler = BleEventHandler(host)

    handler.handle_connect()

    assert host._ui_feedback.errors == ["error.wait_scan"]
    assert host._ble.connected_to == []


def test_handle_connect_blocks_while_connection_is_running() -> None:
    host = FakeHost(_connect_in_progress=True)
    handler = BleEventHandler(host)

    handler.handle_connect()

    assert host._ui_feedback.errors == ["error.wait_connect"]
    assert host._ble.connected_to == []


def test_handle_connect_requires_found_devices() -> None:
    host = FakeHost()
    handler = BleEventHandler(host)

    handler.handle_connect()

    assert host._ui_feedback.errors == ["error.find_first"]
    assert host._ble.connected_to == []


def test_handle_connect_requires_selected_device() -> None:
    host = FakeHost(_devices=[{"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF", "rssi": -50}])
    host.device_combo.setCurrentIndex(-1)
    handler = BleEventHandler(host)

    handler.handle_connect()

    assert host._ui_feedback.errors == ["error.select_controller_first"]
    assert host._ble.connected_to == []


def test_handle_connect_marks_connection_in_progress() -> None:
    host = FakeHost(_devices=[{"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF", "rssi": -50}])
    host.device_combo.addItem("ELK-BLEDOM", "AA:BB:CC:DD:EE:FF")
    handler = BleEventHandler(host)

    handler.handle_connect()

    assert host._connect_in_progress is True
    assert host.device_status.text == "device.status.connecting"
    assert host.scan_button.enabled is False
    assert host.connect_button.enabled is False
    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:FF"]


def test_start_autoconnect_connects_to_saved_address() -> None:
    host = FakeHost(_settings={"last_device_address": "AA:BB:CC:DD:EE:FF", "last_device_name": "Desk strip"})
    handler = BleEventHandler(host)

    handler.start_autoconnect()

    assert host.device_status.text == "device.status.connecting"
    assert host.last_device_label.text == "device.last.autoconnecting:name=Desk strip,address=AA:BB:CC:DD:EE:FF"
    assert host._devices == [{"name": "Desk strip", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-"}]
    assert host.device_combo.items == [("Desk strip  |  AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF")]
    assert host.device_combo.currentIndex() == 0
    assert host._connect_in_progress is True
    assert host.scan_button.enabled is False
    assert host.connect_button.text == "device.connecting"
    assert host._ui_feedback.logs == ["status.autoconnecting:name=Desk strip,address=AA:BB:CC:DD:EE:FF"]
    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:FF"]


def test_start_autoconnect_ignores_empty_or_busy_state() -> None:
    empty_host = FakeHost()
    BleEventHandler(empty_host).start_autoconnect()
    assert empty_host._ble.connected_to == []

    scanning_host = FakeHost(_scan_in_progress=True, _settings={"last_device_address": "AA:BB:CC:DD:EE:FF"})
    BleEventHandler(scanning_host).start_autoconnect()
    assert scanning_host._ble.connected_to == []

    connected_host = FakeHost(_is_connected=True, _settings={"last_device_address": "AA:BB:CC:DD:EE:FF"})
    BleEventHandler(connected_host).start_autoconnect()
    assert connected_host._ble.connected_to == []


def test_start_autoconnect_clears_short_test_address(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(_settings={"last_device_address": "AA:BB", "last_device_name": "Fake"})

    BleEventHandler(host).start_autoconnect()

    assert host._settings["last_device_address"] == ""
    assert host._settings["last_device_name"] == ""
    assert host.last_device_label.text == "device.last.none"
    assert host._ble.connected_to == []
    assert saved == [{"last_device_address": "", "last_device_name": ""}]


def test_last_device_hint_handles_empty_and_saved_state() -> None:
    empty_host = FakeHost()
    BleEventHandler(empty_host)._sync_last_device_hint()
    assert empty_host.last_device_label.text == "device.last.none"
    assert empty_host.device_onboarding_label.text == "device.onboarding_hint"
    assert empty_host.device_onboarding_label.visible is True

    saved_host = FakeHost(_settings={"last_device_address": "AA:BB:CC:DD:EE:FF", "last_device_name": "Desk strip"})
    BleEventHandler(saved_host)._sync_last_device_hint()
    assert saved_host.last_device_label.text == "device.last:name=Desk strip,address=AA:BB:CC:DD:EE:FF"
    assert saved_host.device_onboarding_label.visible is False


def test_populate_devices_autoconnects_single_device() -> None:
    host = FakeHost()
    handler = BleEventHandler(host)
    devices = [{"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF", "rssi": -50}]

    handler.populate_devices(devices)

    assert host._scan_in_progress is False
    assert host.connect_button.enabled is False
    assert host.connect_button.visible is True
    assert host.disconnect_button.enabled is False
    assert host.disconnect_button.visible is False
    assert host.device_status.text == "device.status.connecting"
    assert host._connect_in_progress is True
    assert host.scan_button.enabled is False
    assert host.connect_button.text == "device.connecting"
    assert host.last_device_label.text == "device.last.autoconnecting:name=ELK-BLEDOM,address=AA:BB:CC:DD:EE:FF"
    assert host._ui_feedback.logs == ["status.autofound_connecting:name=ELK-BLEDOM,address=AA:BB:CC:DD:EE:FF"]
    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:FF"]


def test_populate_devices_uses_preferred_device_without_autoconnecting_many() -> None:
    host = FakeHost(_settings={"last_device_address": "BB:CC:DD:EE:FF:00"})
    handler = BleEventHandler(host)
    devices = [
        {"name": "First", "address": "AA:BB:CC:DD:EE:FF", "rssi": -40},
        {"name": "Second", "address": "BB:CC:DD:EE:FF:00", "rssi": -60},
    ]

    handler.populate_devices(devices)

    assert host.device_combo.currentIndex() == 1
    assert host.device_status.text == "device.status.found_many:count=2"
    assert host._ble.connected_to == []


def test_populate_devices_autoconnects_single_supported_among_unknowns() -> None:
    # A lone supported controller should auto-connect even when unrecognised BLE
    # devices are also in the list (there usually are several nearby).
    host = FakeHost()
    handler = BleEventHandler(host)
    devices = [
        {"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF", "rssi": -50, "supported": True},
        {"name": "Unknown BLE Device", "address": "11:22:33:44:55:66", "rssi": -70, "supported": False},
        {"name": "net", "address": "AC:93:C4:1B:B9:1D", "rssi": -90, "supported": False},
    ]

    handler.populate_devices(devices)

    assert host._connect_in_progress is True
    assert host.device_status.text == "device.status.connecting"
    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:FF"]


def test_populate_devices_only_unknown_does_not_autoconnect() -> None:
    host = FakeHost()
    handler = BleEventHandler(host)
    devices = [
        {"name": "Unknown BLE Device", "address": "11:22:33:44:55:66", "rssi": -70, "supported": False},
    ]

    handler.populate_devices(devices)

    assert host._ble.connected_to == []
    assert host.device_status.text == "device.status.found_unknown"


def test_populate_devices_handles_empty_result() -> None:
    host = FakeHost()
    handler = BleEventHandler(host)

    handler.populate_devices([])

    assert host.device_combo.items == [("device.choice.not_found", None)]
    assert host.device_status.text == "device.status.not_found"
    assert host.connect_button.enabled is False
    assert host.connect_button.visible is True
    assert host.disconnect_button.enabled is False
    assert host.disconnect_button.visible is False


def test_connected_changed_saves_address_and_refreshes_ui(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(_devices=[{"address": "AA:BB:CC:DD:EE:FF"}])
    handler = BleEventHandler(host)

    handler.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")

    assert host._is_connected is True
    assert host._connect_in_progress is False
    assert host.device_status.text == "device.status.connected"
    assert host.connect_button.enabled is False
    assert host.connect_button.visible is False
    assert host.disconnect_button.enabled is True
    assert host.disconnect_button.visible is True
    assert host.logs_toggle_button.visible is True
    assert host.effect_refresh_count == 1
    assert host.quick_refresh_count == 1
    assert host._settings["last_device_address"] == "AA:BB:CC:DD:EE:FF"
    assert saved == [{"last_device_address": "AA:BB:CC:DD:EE:FF"}]


def test_connected_changed_saves_device_name_when_known(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(_devices=[{"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF"}])
    handler = BleEventHandler(host)

    handler.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")

    assert host._settings["last_device_address"] == "AA:BB:CC:DD:EE:FF"
    assert host._settings["last_device_name"] == "ELK-BLEDOM"
    assert host.last_device_label.text == "device.last:name=ELK-BLEDOM,address=AA:BB:CC:DD:EE:FF"
    assert saved == [{"last_device_address": "AA:BB:CC:DD:EE:FF", "last_device_name": "ELK-BLEDOM"}]


def test_connected_changed_fills_combo_when_connected_without_scan(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(_settings={"last_device_name": "Desk strip"})
    handler = BleEventHandler(host)

    handler.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")

    assert host.device_combo.items == [("Desk strip  |  AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF")]
    assert host.device_combo.currentIndex() == 0
    assert host._devices == [{"name": "Desk strip", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-"}]


def test_connected_changed_disconnected_state_does_not_save(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(_devices=[{"address": "AA:BB:CC:DD:EE:FF"}])
    handler = BleEventHandler(host)

    handler.on_connected_changed(False, "")

    assert host._is_connected is False
    assert host.device_status.text == "device.status.not_connected"
    assert host.connect_button.enabled is True
    assert host.connect_button.visible is True
    assert host.disconnect_button.enabled is False
    assert host.disconnect_button.visible is False
    assert host.logs_toggle_button.visible is False
    assert saved == []


def test_show_error_clears_connection_in_progress() -> None:
    host = FakeHost(_connect_in_progress=True, _settings={"last_device_address": "AA:BB:CC:DD:EE:FF", "last_device_name": "Desk strip"})
    handler = BleEventHandler(host)
    host.device_status.setText("device.status.connecting")

    handler.show_error("boom")

    assert host._connect_in_progress is False
    assert host._scan_in_progress is False
    assert host.device_status.text == "device.status.not_connected"
    assert host.scan_button.enabled is True
    assert host.connect_button.text == "device.connect"
    assert host.last_device_label.text == "device.last:name=Desk strip,address=AA:BB:CC:DD:EE:FF"
    assert host._ui_feedback.errors == ["boom"]


def test_device_label_skips_duplicate_address_and_empty_rssi() -> None:
    handler = BleEventHandler(FakeHost())
    # Unresolved name (equals the address) -> shown once, no "RSSI -" tail.
    assert (
        handler._device_label({"name": "AA:BB:CC:DD:EE:FF", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-"})
        == "AA:BB:CC:DD:EE:FF"
    )
    # Distinct name + a real RSSI reading -> all three parts.
    assert (
        handler._device_label({"name": "Desk strip", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-42"})
        == "Desk strip  |  AA:BB:CC:DD:EE:FF  |  RSSI -42"
    )

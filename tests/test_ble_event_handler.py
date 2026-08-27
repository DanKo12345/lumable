from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtWidgets import QApplication

from app import ble_event_handler
from app.ble_event_handler import BleEventHandler
from app.scan_choices import address_of, device_choice
from app.widgets.static_popup_combo_box import StaticPopupComboBox


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

    def currentData(self) -> Any:
        """What the highlighted row carries — Qt's own answer, not a shortcut.

        Spelled out rather than left off: the code under test now asks the row
        what it stands for, and a stand-in that could not be asked would have
        sent that question nowhere.
        """
        return self.itemData(self.index)

    def setCurrentIndex(self, index: int) -> None:
        self.index = index

    def findData(self, data: Any) -> int:
        for index, item in enumerate(self.items):
            if item[1] == data:
                return index
        return -1

    def count(self) -> int:
        return len(self.items)

    def itemData(self, index: int) -> Any:
        if 0 <= index < len(self.items):
            return self.items[index][1]
        return None

    def itemText(self, index: int) -> str:
        if 0 <= index < len(self.items):
            return self.items[index][0]
        return ""

    def setItemText(self, index: int, text: str) -> None:
        if 0 <= index < len(self.items):
            self.items[index] = (text, self.items[index][1])


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
        self.restored: list[str] = []
        self.mirrored: list[str] = []
        self.inspected: list[str] = []

    def scan(self) -> None:
        self.scan_called = True

    def connect_to_address(self, address: str) -> None:
        self.connected_to.append(address)

    # Part of the real BleController surface the handler relies on.
    def mirror_addresses(self) -> list[str]:
        return []

    def restore_mirror_device(self, address: str) -> None:
        self.restored.append(address)

    def add_mirror_device(self, address: str) -> None:
        self.mirrored.append(address)

    def inspect_device(self, address: str, name: str = "", *, token: int = 0) -> None:
        """A read-only compatibility check. Records the ask; answers later."""
        self.inspected.append(address)


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
    # A read-only compatibility check, tracked apart from a connection.
    _inspect_in_progress: bool = False
    _inspection_token: int = 0
    _device_problem: str = ""

    def _clear_device_problem(self) -> None:
        self._device_problem = ""
    _settings: dict[str, Any] = field(default_factory=dict)
    _ui_feedback: FakeFeedback = field(default_factory=FakeFeedback)

    device_combo: FakeCombo = field(default_factory=FakeCombo)
    device_status: FakeLabel = field(default_factory=FakeLabel)
    device_status_hint: FakeLabel = field(default_factory=FakeLabel)
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
    assert [text for text, _ in host.device_combo.items] == ["device.choice.scan_placeholder"]
    assert address_of(host.device_combo.itemData(0)) == "", "a placeholder offered itself as a strip"
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
    host.device_combo.addItem("ELK-BLEDOM", device_choice("AA:BB:CC:DD:EE:FF"))
    handler = BleEventHandler(host)

    handler.handle_connect()

    assert host._connect_in_progress is True
    assert host.device_status.text == "device.status.connecting"
    assert host.scan_button.enabled is False
    assert host.connect_button.enabled is False
    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:FF"]


def test_start_autoconnect_connects_to_saved_address() -> None:
    host = FakeHost(
        _settings={
            "last_device_address": "AA:BB:CC:DD:EE:FF",
            "last_device_name": "Desk strip",
            # Chosen at some point, which is what makes reaching for it again
            # a convenience rather than a guess.
            "trusted_device_addresses": ["AA:BB:CC:DD:EE:FF"],
        }
    )
    handler = BleEventHandler(host)

    handler.start_autoconnect()

    assert host.device_status.text == "device.status.connecting"
    assert host.last_device_label.text == "device.last.autoconnecting:name=Desk strip,address=AA:BB:CC:DD:EE:FF"
    assert host._devices == [{"name": "Desk strip", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-"}]
    assert [text for text, _ in host.device_combo.items] == ["Desk strip  |  AA:BB:CC:DD:EE:FF"]
    assert address_of(host.device_combo.itemData(0)) == "AA:BB:CC:DD:EE:FF"
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


def test_populate_devices_autoconnects_single_trusted_device() -> None:
    host = FakeHost(_settings={"trusted_device_addresses": ["AA:BB:CC:DD:EE:FF"]})
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


def test_populate_devices_selects_preferred_among_many_without_connecting() -> None:
    host = FakeHost(_settings={"last_device_address": "BB:CC:DD:EE:FF:00"})
    handler = BleEventHandler(host)
    devices = [
        {"name": "First", "address": "AA:BB:CC:DD:EE:FF", "rssi": -40},
        {"name": "Second", "address": "BB:CC:DD:EE:FF:00", "rssi": -60},
    ]

    handler.populate_devices(devices)

    assert host.device_combo.currentIndex() == 1
    assert host.device_status.text == "device.status.found_many:count=2"
    assert host._connect_in_progress is False
    assert host._ble.connected_to == []


def test_scan_can_be_read_only_even_with_one_supported_device() -> None:
    host = FakeHost()
    handler = BleEventHandler(host)

    handler.start_scan(auto_connect=False)
    handler.populate_devices(
        [{"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF", "rssi": -40}]
    )

    assert host.device_combo.currentIndex() == 0
    assert host._connect_in_progress is False
    assert host._ble.connected_to == []


def test_read_only_scan_policy_does_not_leak_into_the_next_manual_scan() -> None:
    host = FakeHost(_settings={"trusted_device_addresses": ["AA:BB:CC:DD:EE:FF"]})
    handler = BleEventHandler(host)
    device = {"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF", "rssi": -40}

    handler.start_scan(auto_connect=False)
    handler.populate_devices([device])
    handler.start_scan()
    handler.populate_devices([device])

    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:FF"]


def test_status_click_connects_the_selected_scan_result_instead_of_rescanning() -> None:
    host = FakeHost()
    handler = BleEventHandler(host)
    devices = [
        {"name": "First", "address": "AA:BB:CC:DD:EE:FF", "rssi": -40},
        {"name": "Second", "address": "BB:CC:DD:EE:FF:00", "rssi": -60},
    ]
    handler.populate_devices(devices)
    assert host.device_status.text == "device.status.found_many:count=2"

    handler.connect_or_scan()

    assert host._ble.scan_called is False
    assert host._connect_in_progress is True
    assert host.device_status.text == "device.status.connecting"
    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:FF"]


def test_populate_devices_autoconnects_single_supported_among_unknowns() -> None:
    # A lone supported controller that this person has chosen before should
    # auto-connect even when unrecognised BLE devices are also in the list
    # (there usually are several nearby).
    host = FakeHost(_settings={"trusted_device_addresses": ["AA:BB:CC:DD:EE:FF"]})
    handler = BleEventHandler(host)
    devices = [
        {"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF", "rssi": -50, "supported": True},
        {"name": "Unknown BLE Device", "address": "11:22:33:44:55:66", "rssi": -70, "supported": False},
        {"name": "net", "address": "AA:BB:CC:DD:EE:03", "rssi": -90, "supported": False},
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

    assert [text for text, _ in host.device_combo.items] == ["device.choice.not_found"]
    assert address_of(host.device_combo.itemData(0)) == "", "a placeholder offered itself as a strip"
    assert host.device_status.text == "device.status.not_found"
    assert host.connect_button.enabled is False
    assert host.connect_button.visible is True
    assert host.disconnect_button.enabled is False
    assert host.disconnect_button.visible is False


def test_connected_changed_saves_address_and_refreshes_ui(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(
        _devices=[{"address": "AA:BB:CC:DD:EE:FF"}],
        _settings={"trusted_device_addresses": ["AA:BB:CC:DD:EE:FF"]},
    )
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
    assert saved[-1]["last_device_address"] == "AA:BB:CC:DD:EE:FF"


def test_connected_changed_saves_device_name_when_known(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(
        _devices=[{"name": "ELK-BLEDOM", "address": "AA:BB:CC:DD:EE:FF"}],
        # An already-chosen strip coming back. What a *newly* chosen one does,
        # and what an unchosen one is refused, live in their own tests.
        _settings={"trusted_device_addresses": ["AA:BB:CC:DD:EE:FF"]},
    )
    handler = BleEventHandler(host)

    handler.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")

    assert host._settings["last_device_address"] == "AA:BB:CC:DD:EE:FF"
    assert host._settings["last_device_name"] == "ELK-BLEDOM"
    assert host.last_device_label.text == "device.last:name=ELK-BLEDOM,address=AA:BB:CC:DD:EE:FF"
    assert saved[-1]["last_device_address"] == "AA:BB:CC:DD:EE:FF"
    assert saved[-1]["last_device_name"] == "ELK-BLEDOM"


def test_connected_changed_fills_combo_when_connected_without_scan(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(_settings={"last_device_name": "Desk strip"})
    handler = BleEventHandler(host)

    handler.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")

    assert [text for text, _ in host.device_combo.items] == ["Desk strip  |  AA:BB:CC:DD:EE:FF"]
    assert address_of(host.device_combo.itemData(0)) == "AA:BB:CC:DD:EE:FF"
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


def test_device_label_skips_a_duplicate_address_and_says_nothing_it_cannot() -> None:
    handler = BleEventHandler(FakeHost())
    # Unresolved name (equals the address) -> shown once. Nothing was heard,
    # so nothing is said about the signal either.
    assert (
        handler._device_label(
            {"name": "AA:BB:CC:DD:EE:FF", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-"}
        )
        == "AA:BB:CC:DD:EE:FF"
    )
    # A distinct name and a scan's worth of readings -> all three parts, and the
    # third one is a sentence rather than a figure.
    assert (
        handler._device_label(
            {
                "name": "Desk strip",
                "address": "AA:BB:CC:DD:EE:FF",
                "rssi": "-42",
                "rssi_samples": (-42, -43, -41),
            }
        )
        == "Desk strip  |  AA:BB:CC:DD:EE:FF  |  device.signal.strong"
    )


def test_no_decibels_reach_the_ordinary_label() -> None:
    """The figure is kept for the report. In the picker it is a number almost
    nobody can act on, sitting where the useful sentence goes."""
    handler = BleEventHandler(FakeHost())

    label = handler._device_label(
        {
            "name": "Desk strip",
            "address": "AA:BB:CC:DD:EE:FF",
            "rssi": "-67",
            "rssi_samples": (-67, -68, -66),
        }
    )

    assert "-67" not in label
    assert "RSSI" not in label
    assert "dBm" not in label


class FakeSignalSink:
    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def fire(self, *args: Any) -> None:
        for slot in list(self._slots):
            slot(*args)


class PromoteBle(FakeBle):
    def __init__(self, mirrors: list[str] | None = None) -> None:
        super().__init__()
        self.mirrors = list(mirrors or [])
        self.promoted: list[str] = []

    def mirror_addresses(self) -> list[str]:
        return list(self.mirrors)

    def promote_mirror_to_primary(self, address: str, *, keep_old_as_extra: bool = True) -> None:
        self.promoted.append(address)
        self.kept_old = keep_old_as_extra


class FakeSceneUi:
    def __init__(self) -> None:
        self.refreshed = 0

    def refresh(self) -> None:
        self.refreshed += 1


def test_primary_changed_saves_the_new_main_strip(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(
        _ble=PromoteBle(["AA:BB:CC:DD:EE:FF"]),
        _settings={"last_device_address": "AA:BB:CC:DD:EE:FF", "last_device_name": "Desk"},
        _is_connected=True,
    )
    host.device_status_hint.setText("Desk")
    host._scene_ui = FakeSceneUi()
    host._devices = [
        {"name": "Desk", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-45"},
        {"name": "TV", "address": "11:22:33:44:55:66", "rssi": "-55"},
    ]
    for device in host._devices:
        host.device_combo.addItem(device["name"], device_choice(device["address"]))
    host.device_combo.setCurrentIndex(0)
    handler = BleEventHandler(host)

    handler.on_primary_changed("11:22:33:44:55:66", "TV")

    assert host._settings["last_device_address"] == "11:22:33:44:55:66"
    assert host._settings["last_device_name"] == "TV"
    assert saved and saved[-1]["last_device_address"] == "11:22:33:44:55:66"
    assert host.last_device_label.text == "device.last:name=TV,address=11:22:33:44:55:66"
    assert host.device_status_hint.text == "TV"
    assert address_of(host.device_combo.currentData()) == "11:22:33:44:55:66"
    # Scene targets ("primary", groups) follow the new main strip.
    assert host._scene_ui.refreshed == 1


def test_primary_changed_adds_and_selects_a_primary_missing_from_scan_results(monkeypatch) -> None:
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: None)
    old = {"name": "Desk", "address": "AA:BB:CC:DD:EE:FF", "rssi": "-45"}
    host = FakeHost(
        _ble=PromoteBle([old["address"]]),
        _devices=[old],
        _settings={"last_device_address": old["address"], "last_device_name": old["name"]},
        _is_connected=True,
    )
    host.device_combo.addItem("Desk", device_choice(old["address"]))

    BleEventHandler(host).on_primary_changed("11:22:33:44:55:66", "TV")

    assert address_of(host.device_combo.currentData()) == "11:22:33:44:55:66"
    assert any(device["address"] == "11:22:33:44:55:66" for device in host._devices)


def test_empty_mirror_scan_restores_visible_primary_in_real_combo(monkeypatch) -> None:
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: None)
    QApplication.instance() or QApplication([])
    primary = "BE:68:3D:0C:5C:03"
    host = FakeHost(
        _ble=PromoteBle([]),
        _settings={"last_device_address": primary, "last_device_name": "ELK-BLEDOM CE"},
        _is_connected=True,
    )
    host.device_combo = StaticPopupComboBox(lambda: {}, lambda: True)
    handler = BleEventHandler(host)

    handler._handle_mirror_scan_result([])

    assert address_of(host.device_combo.currentData()) == primary
    assert host.device_combo.currentText() == "ELK-BLEDOM CE  |  BE:68:3D:0C:5C:03"


def test_mirror_refresh_returns_picker_from_extra_to_primary(monkeypatch) -> None:
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: None)
    primary = "BE:68:3D:0C:5C:03"
    extra = "BE:68:46:09:19:00"
    host = FakeHost(
        _ble=PromoteBle([extra]),
        _devices=[{"name": "ELK-BLEDOM 8E", "address": extra, "rssi": "-87"}],
        _settings={"last_device_address": primary, "last_device_name": "ELK-BLEDOM CE"},
        _is_connected=True,
    )
    host.device_combo.addItem("ELK-BLEDOM 8E", device_choice(extra))
    handler = BleEventHandler(host)

    # mirrors_changed arrives after the extra was accepted.
    handler.refresh_mirror_list([extra])

    assert address_of(host.device_combo.currentData()) == primary


def test_mirror_candidates_compare_addresses_case_insensitively() -> None:
    primary = "BE:68:3D:0C:5C:03"
    extra = "BE:68:46:09:19:00"
    host = FakeHost(
        _ble=PromoteBle([extra.lower()]),
        _devices=[
            {"name": "Primary", "address": primary.lower(), "supported": True},
            {"name": "Extra", "address": extra, "supported": True},
        ],
        _settings={"last_device_address": primary},
        _is_connected=True,
    )

    assert BleEventHandler(host)._has_mirror_candidate() is False


def test_primary_changed_prefers_the_saved_custom_name(monkeypatch) -> None:
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: None)
    host = FakeHost(
        _ble=PromoteBle([]),
        _settings={"device_names": {"11:22:33:44:55:66": "Bedroom"}},
    )
    handler = BleEventHandler(host)

    handler.on_primary_changed("11:22:33:44:55:66", "ELK-BLEDOM")

    assert host._settings["last_device_name"] == "Bedroom"


def test_primary_changed_ignores_an_empty_address(monkeypatch) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: saved.append(dict(settings)))
    host = FakeHost(_ble=PromoteBle([]), _settings={"last_device_address": "AA:BB:CC:DD:EE:FF"})
    handler = BleEventHandler(host)

    handler.on_primary_changed("", "")

    assert host._settings["last_device_address"] == "AA:BB:CC:DD:EE:FF"
    assert saved == []


def test_primary_change_survives_a_restart(monkeypatch) -> None:
    """After a swap the app must autoconnect to the new main strip."""
    stored: dict[str, Any] = {}
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: stored.update(settings))
    host = FakeHost(
        _ble=PromoteBle(["AA:BB:CC:DD:EE:FF"]),
        _settings={"last_device_address": "AA:BB:CC:DD:EE:FF", "last_device_name": "Desk"},
    )
    BleEventHandler(host).on_primary_changed("11:22:33:44:55:66", "TV")

    # Fresh launch reading the persisted settings.
    restarted = FakeHost(_ble=PromoteBle([]), _settings=dict(stored))
    restarted_handler = BleEventHandler(restarted)
    restarted_handler._sync_last_device_hint()

    assert restarted._settings["last_device_address"] == "11:22:33:44:55:66"
    assert restarted.last_device_label.text == "device.last:name=TV,address=11:22:33:44:55:66"


def test_promote_device_asks_before_swapping_roles() -> None:
    host = FakeHost(_ble=PromoteBle(["11:22:33:44:55:66"]))
    handler = BleEventHandler(host)
    opened: list[Any] = []

    class FakeConfirmOverlay:
        def __init__(
            self,
            labels: dict[str, str],
            parent: Any,
            *,
            confirm_role: str = "accent",
            toggle_label: str = "",
            toggle_checked: bool = True,
        ) -> None:
            self.labels = labels
            self.toggle_label = toggle_label
            self._checked = toggle_checked
            self.confirmed = FakeSignalSink()
            self.closed = FakeSignalSink()
            opened.append(self)

        def toggle_checked(self) -> bool:
            return self._checked

        def open(self) -> None:
            self.is_open = True

    original = ble_event_handler.ProfileConfirmOverlay
    ble_event_handler.ProfileConfirmOverlay = FakeConfirmOverlay
    try:
        handler.promote_device("11:22:33:44:55:66", "TV")
        assert len(opened) == 1
        assert opened[0].labels["message"] == "device.make_primary_confirm:name=TV"
        # The fate of the current main strip is offered as a choice, on by default.
        assert opened[0].toggle_label.startswith("device.keep_old_primary")
        # Nothing happens until the user confirms.
        assert host._ble.promoted == []
        opened[0].confirmed.fire()
        assert host._ble.promoted == ["11:22:33:44:55:66"]
        assert host._ble.kept_old is True
        # A second click while the overlay is up must not stack overlays.
        handler.promote_device("11:22:33:44:55:66", "TV")
        assert len(opened) == 1
    finally:
        ble_event_handler.ProfileConfirmOverlay = original


def test_promote_device_can_drop_the_old_primary() -> None:
    """Unticking the toggle means "switch over": the old main strip is dropped."""
    host = FakeHost(_ble=PromoteBle(["11:22:33:44:55:66"]))
    handler = BleEventHandler(host)
    opened: list[Any] = []

    class FakeConfirmOverlay:
        def __init__(self, labels: dict[str, str], parent: Any, **kwargs: Any) -> None:
            self.confirmed = FakeSignalSink()
            self.closed = FakeSignalSink()
            opened.append(self)

        def toggle_checked(self) -> bool:
            return False  # user unticked "keep the old one connected"

        def open(self) -> None:
            self.is_open = True

    original = ble_event_handler.ProfileConfirmOverlay
    ble_event_handler.ProfileConfirmOverlay = FakeConfirmOverlay
    try:
        handler.promote_device("11:22:33:44:55:66", "TV")
        opened[0].confirmed.fire()
        assert host._ble.promoted == ["11:22:33:44:55:66"]
        assert host._ble.kept_old is False
    finally:
        ble_event_handler.ProfileConfirmOverlay = original

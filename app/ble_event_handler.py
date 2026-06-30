from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.storage import save_settings
from app.types import BleEventHost


def _is_plausible_ble_address(address: str) -> bool:
    text = str(address).strip()
    if not text:
        return False
    parts = text.split(":")
    if len(parts) == 6:
        hex_digits = set("0123456789abcdefABCDEF")
        return all(len(part) == 2 and all(char in hex_digits for char in part) for part in parts)
    return len(text) >= 12


class BleEventHandler:
    def __init__(self, host: BleEventHost) -> None:
        self._host = host
        self._mirror_scan_pending = False

    def start_scan(self) -> None:
        host = self._host
        if host._is_connected:
            self.show_error(host._tr("error.disconnect_before_scan"))
            return
        if host._connect_in_progress:
            self.show_error(host._tr("error.wait_connect"))
            return
        host._scan_in_progress = True
        host._devices = []
        host.device_combo.clear()
        host.device_combo.addItem(host._tr("device.choice.scan_placeholder"))
        host.device_status.setText(host._tr("device.status.scanning"))
        self._sync_last_device_hint()
        self._sync_device_onboarding_hint()
        host._sync_connect_buttons()
        host._ble.scan()

    def handle_connect(self) -> None:
        host = self._host
        if host._scan_in_progress:
            self.show_error(host._tr("error.wait_scan"))
            return
        if host._connect_in_progress:
            self.show_error(host._tr("error.wait_connect"))
            return
        index = host.device_combo.currentIndex()
        if not host._devices:
            self.show_error(host._tr("error.find_first"))
            return
        if index < 0 or index >= len(host._devices):
            self.show_error(host._tr("error.select_controller_first"))
            return
        host._connect_in_progress = True
        host.device_status.setText(host._tr("device.status.connecting"))
        host._sync_connect_buttons()
        host._ble.connect_to_address(host._devices[index]["address"])

    def start_autoconnect(self) -> None:
        host = self._host
        if host._is_connected or host._scan_in_progress or host._connect_in_progress:
            return
        address = str(host._settings.get("last_device_address", "")).strip()
        if not address:
            return
        if not _is_plausible_ble_address(address):
            host._settings["last_device_address"] = ""
            host._settings["last_device_name"] = ""
            save_settings(host._settings)
            self._sync_last_device_hint()
            return
        name = str(host._settings.get("last_device_name", "")).strip()
        display_name = name or address
        host._devices = [{"name": display_name, "address": address, "rssi": "-"}]
        host.device_combo.clear()
        host.device_combo.addItem(self._device_label(host._devices[0]), address)
        host.device_combo.setCurrentIndex(0)
        host._connect_in_progress = True
        host.device_status.setText(host._tr("device.status.connecting"))
        self._sync_last_device_hint(name=display_name, address=address, autoconnecting=True)
        host._sync_connect_buttons()
        self.log(host._tr("status.autoconnecting", name=display_name, address=address))
        host._ble.connect_to_address(address)

    def populate_devices(self, devices: list[dict[str, Any]]) -> None:
        host = self._host
        host._scan_in_progress = False
        if getattr(self, "_mirror_scan_pending", False):
            # This scan was triggered by "Add strip" while already connected —
            # don't touch the primary connect flow, just add the found mirror.
            self._mirror_scan_pending = False
            self._handle_mirror_scan_result(devices)
            return
        host._devices = devices
        host.device_combo.clear()
        if not devices:
            host.device_combo.addItem(host._tr("device.choice.not_found"))
            host.device_status.setText(host._tr("device.status.not_found"))
            self._sync_last_device_hint()
            self._sync_device_onboarding_hint()
            host._sync_connect_buttons()
            return
        for device in devices:
            host.device_combo.addItem(self._device_label(device), device["address"])
        supported = [device for device in devices if device.get("supported", True)]
        preferred = host._settings.get("last_device_address", "")
        preferred_index = host.device_combo.findData(preferred) if preferred else -1
        host.device_combo.setCurrentIndex(preferred_index if preferred_index >= 0 else 0)
        if preferred_index >= 0:
            preferred_device = devices[preferred_index]
            self._sync_last_device_hint(
                name=str(preferred_device.get("name", "")).strip(),
                address=str(preferred_device.get("address", "")).strip(),
            )
        else:
            self._sync_last_device_hint()
        self._sync_device_onboarding_hint()
        host._sync_connect_buttons()
        # Auto-connect when exactly one *supported* controller is found, even if
        # unrecognised BLE devices are also nearby (there usually are several).
        # Unknown devices are never auto-connected — the user picks one to probe.
        if len(supported) == 1:
            device = supported[0]
            index = host.device_combo.findData(device["address"])
            if index >= 0:
                host.device_combo.setCurrentIndex(index)
            self.log(host._tr("status.autofound_connecting", name=device["name"], address=device["address"]))
            host._connect_in_progress = True
            host.device_status.setText(host._tr("device.status.connecting"))
            self._sync_last_device_hint(name=str(device.get("name", "")).strip(), address=str(device.get("address", "")).strip(), autoconnecting=True)
            self._sync_device_onboarding_hint()
            host._sync_connect_buttons()
            host._ble.connect_to_address(device["address"])
        elif supported:
            host.device_status.setText(host._tr("device.status.found_many", count=len(supported)))
        else:
            # Only unrecognised devices nearby — invite the user to probe one.
            host.device_status.setText(host._tr("device.status.found_unknown"))

    def on_connected_changed(self, connected: bool, address: str) -> None:
        host = self._host
        host._is_connected = connected
        host._connect_in_progress = False
        add_mirror = getattr(host, "add_mirror_button", None)
        if add_mirror is not None:
            add_mirror.setEnabled(connected)
        host.device_status.setText(host._tr("device.status.connected") if connected else host._tr("device.status.not_connected"))
        update_dot = getattr(host, "_update_status_dot", None)
        if callable(update_dot):
            update_dot()
        hint = getattr(host, "device_status_hint", None)
        if hint is not None:
            if connected:
                name = self._device_name_for_address(address) or address or ""
                hint.setText(name)
                hint.setVisible(bool(name))
            else:
                hint.setText(host._tr("device.connect_hint"))
                hint.setVisible(True)
        sync_power_button = getattr(host, "_sync_power_button", None)
        if callable(sync_power_button):
            sync_power_button()
        host._sync_connect_buttons()
        host._refresh_effect_names()
        host._refresh_quick_mode_buttons()
        if connected and _is_plausible_ble_address(address):
            if address and host.device_combo.findData(address) < 0:
                display_name = self._device_name_for_address(address) or address
                device = {"name": display_name, "address": address, "rssi": "-"}
                host._devices = [device]
                host.device_combo.clear()
                host.device_combo.addItem(self._device_label(device), address)
                host.device_combo.setCurrentIndex(0)
            host._settings["last_device_address"] = address
            device_name = self._device_name_for_address(address)
            if device_name and device_name != address:
                host._settings["last_device_name"] = device_name
            self._sync_last_device_hint(name=device_name or address, address=address)
            save_settings(host._settings)
        elif not host._connect_in_progress:
            self._sync_last_device_hint()
        self._sync_device_onboarding_hint()

    def _device_name_for_address(self, address: str) -> str:
        for device in self._host._devices:
            if str(device.get("address", "")).strip() == address:
                return str(device.get("name", "")).strip()
        return str(self._host._settings.get("last_device_name", "")).strip()

    def _device_label(self, device: dict[str, Any]) -> str:
        name = str(device.get("name", "")).strip()
        address = str(device.get("address", "")).strip()
        rssi = str(device.get("rssi", "")).strip()
        parts: list[str] = []
        # Skip the name when it's just the address again (avoids "MAC | MAC").
        if name and name != address:
            parts.append(name)
        if address:
            parts.append(address)
        # Only show RSSI when there's a real reading (not the "-" placeholder).
        if rssi and rssi != "-":
            parts.append(f"RSSI {rssi}")
        label = "  |  ".join(parts) if parts else address
        # Flag controllers we don't recognise yet so the choice is clear.
        if device.get("supported", True) is False:
            label = f"{label}  ·  {self._host._tr('device.unsupported_tag')}"
        return label

    def _sync_last_device_hint(
        self,
        *,
        name: str | None = None,
        address: str | None = None,
        autoconnecting: bool = False,
    ) -> None:
        label = getattr(self._host, "last_device_label", None)
        if label is None:
            return
        host = self._host
        resolved_address = str(address if address is not None else host._settings.get("last_device_address", "")).strip()
        resolved_name = str(name if name is not None else host._settings.get("last_device_name", "")).strip()
        if not resolved_address:
            label.setText(host._tr("device.last.none"))
            self._sync_device_onboarding_hint()
            return
        # When there's no distinct name (it equals the address), use the plain
        # variant so the line isn't "MAC / MAC".
        has_name = bool(resolved_name) and resolved_name != resolved_address
        if autoconnecting:
            key = "device.last.autoconnecting" if has_name else "device.last.autoconnecting_plain"
        else:
            key = "device.last" if has_name else "device.last_plain"
        label.setText(host._tr(key, name=resolved_name, address=resolved_address))
        self._sync_device_onboarding_hint()

    def _sync_device_onboarding_hint(self) -> None:
        label = getattr(self._host, "device_onboarding_label", None)
        if label is None:
            return
        host = self._host
        has_last_device = bool(str(host._settings.get("last_device_address", "")).strip())
        should_show = not any((
            has_last_device,
            host._is_connected,
            host._scan_in_progress,
            host._connect_in_progress,
            bool(host._devices),
        ))
        label.setText(host._tr("device.onboarding_hint"))
        label.setVisible(should_show)

    def show_error(self, message: str) -> None:
        self._host._connect_in_progress = False
        self._host._scan_in_progress = False
        if not self._host._is_connected:
            self._host.device_status.setText(self._host._tr("device.status.not_connected"))
        self._sync_last_device_hint()
        self._host._sync_connect_buttons()
        self._host._ui_feedback.show_error(message)

    def log(self, message: str) -> None:
        self._host._ui_feedback.log(message)

    def add_selected_as_mirror(self) -> None:
        host = self._host
        if not host._is_connected:
            return
        primary = str(host._settings.get("last_device_address", "")).strip()
        mirrors = set(host._ble.mirror_addresses())

        def is_candidate(device: dict[str, Any]) -> bool:
            address = str(device.get("address", "")).strip()
            return bool(address) and bool(device.get("supported", True)) and address != primary and address not in mirrors

        candidates = [device for device in host._devices if is_candidate(device)]
        if not candidates:
            # Nothing else to mirror — guide the user to scan with the other strip on.
            self.show_error(host._tr("device.mirror_none"))
            return
        # Respect an explicit pick in the list; otherwise auto-pick when there's
        # only one other strip, or ask the user to choose when several.
        index = host.device_combo.currentIndex()
        if 0 <= index < len(host._devices) and is_candidate(host._devices[index]):
            chosen = host._devices[index]
        elif len(candidates) == 1:
            chosen = candidates[0]
        else:
            self.show_error(host._tr("device.mirror_pick_first"))
            return
        host._ble.add_mirror_device(str(chosen.get("address", "")).strip())

    def request_add_mirror(self) -> None:
        """Entry point for the 'Add strip' button: add a known second strip, or
        scan for one first (the scan button is disabled while connected)."""
        host = self._host
        if not host._is_connected:
            return
        if self._has_mirror_candidate():
            self.add_selected_as_mirror()
            return
        self.start_mirror_scan()

    def _has_mirror_candidate(self) -> bool:
        host = self._host
        primary = str(host._settings.get("last_device_address", "")).strip()
        mirrors = set(host._ble.mirror_addresses())
        for device in host._devices:
            address = str(device.get("address", "")).strip()
            if address and device.get("supported", True) and address != primary and address not in mirrors:
                return True
        return False

    def start_mirror_scan(self) -> None:
        host = self._host
        if not host._is_connected or host._connect_in_progress or host._scan_in_progress:
            return
        self._mirror_scan_pending = True
        self.log(host._tr("device.mirror_scanning"))
        host._ble.scan()

    def _handle_mirror_scan_result(self, devices: list[dict[str, Any]]) -> None:
        host = self._host
        host._devices = devices
        host.device_combo.clear()
        for device in devices:
            host.device_combo.addItem(self._device_label(device), device["address"])
        host._sync_connect_buttons()
        self.add_selected_as_mirror()

    def refresh_mirror_list(self, addresses: list[str]) -> None:
        host = self._host
        container = getattr(host, "mirror_list_container", None)
        layout = getattr(host, "mirror_list_layout", None)
        if container is None or layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for address in addresses:
            name = address
            for device in host._devices:
                if str(device.get("address", "")).strip() == address:
                    name = str(device.get("name", "")).strip() or address
                    break
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            label = QLabel(host._tr("device.mirror_item", name=name, address=address))
            label.setObjectName("lastDeviceHint")
            remove = host._button(host._tr("device.mirror_remove"), "ghost")
            remove.clicked.connect(lambda _checked=False, a=address: host._ble.remove_mirror_device(a))
            row_layout.addWidget(label, 1)
            row_layout.addWidget(remove)
            layout.addWidget(row)
        container.setVisible(bool(addresses))

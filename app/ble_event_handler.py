from __future__ import annotations

from typing import Any

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
            host.device_combo.addItem(f"{device['name']}  |  {device['address']}  |  RSSI {device['rssi']}", device["address"])
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
        if len(devices) == 1:
            device = devices[0]
            host.device_status.setText(host._tr("device.status.found_one", name=device["name"]))
            self.log(host._tr("status.autofound_connecting", name=device["name"], address=device["address"]))
            host._connect_in_progress = True
            host.device_status.setText(host._tr("device.status.connecting"))
            self._sync_last_device_hint(name=str(device.get("name", "")).strip(), address=str(device.get("address", "")).strip(), autoconnecting=True)
            self._sync_device_onboarding_hint()
            host._sync_connect_buttons()
            host._ble.connect_to_address(device["address"])
        else:
            host.device_status.setText(host._tr("device.status.found_many", count=len(devices)))

    def on_connected_changed(self, connected: bool, address: str) -> None:
        host = self._host
        host._is_connected = connected
        host._connect_in_progress = False
        host.device_status.setText(host._tr("device.status.connected") if connected else host._tr("device.status.not_connected"))
        dot = getattr(host, "device_status_dot", None)
        if dot is not None:
            dot_color = "#46d39a" if connected else "rgba(255, 255, 255, 0.30)"
            dot.setStyleSheet(f"background: {dot_color}; border-radius: {max(2, dot.width() // 2)}px;")
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
        name = str(device.get("name", "")).strip() or str(device.get("address", "")).strip()
        address = str(device.get("address", "")).strip()
        rssi = str(device.get("rssi", "")).strip() or "-"
        return f"{name}  |  {address}  |  RSSI {rssi}"

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
        display_name = resolved_name or resolved_address
        key = "device.last.autoconnecting" if autoconnecting else "device.last"
        label.setText(host._tr(key, name=display_name, address=resolved_address))
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

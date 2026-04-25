from __future__ import annotations

from app.ble_drivers.base import LedBleDriver, clamp, packet, scale_percent_to_byte
from app.ble_drivers.bledom import TARGET_SERVICE_UUID


def build_power_command(enabled: bool) -> bytes:
    return packet(0xCC, 0x23 if enabled else 0x24, 0x33)


def build_color_command(red: int, green: int, blue: int) -> bytes:
    return packet(0x56, clamp(red, 0, 255), clamp(green, 0, 255), clamp(blue, 0, 255), 0x00, 0xF0, 0xAA)


def build_brightness_command(value_percent: int) -> bytes:
    return packet(0x56, 0x00, 0x00, 0x00, scale_percent_to_byte(value_percent), 0x0F, 0xAA)


class TrionesDriver(LedBleDriver):
    id = "triones"
    display_name = "Triones"
    name_tokens = (
        "triones",
        "happy lighting",
        "happylighting",
        "ledble",
        "led blue",
        "ledblue",
        "zengge",
        "magic blue",
    )
    scan_service_uuids = frozenset(
        {
            "0000ffd0-0000-1000-8000-00805f9b34fb",
            "0000ffd4-0000-1000-8000-00805f9b34fb",
            "0000ffe4-0000-1000-8000-00805f9b34fb",
        }
    )
    known_write_uuids = frozenset(
        {
            "0000ffd5-0000-1000-8000-00805f9b34fb",
            "0000ffd9-0000-1000-8000-00805f9b34fb",
            "0000ffe5-0000-1000-8000-00805f9b34fb",
            "0000ffe9-0000-1000-8000-00805f9b34fb",
        }
    )
    interesting_service_uuids = frozenset(
        {
            "0000ffd0-0000-1000-8000-00805f9b34fb",
            "0000ffd4-0000-1000-8000-00805f9b34fb",
            "0000ffe0-0000-1000-8000-00805f9b34fb",
            "0000ffe4-0000-1000-8000-00805f9b34fb",
        }
    )

    def matches_scan(self, name: str, service_uuids) -> bool:
        lowered_name = (name or "").lower()
        if any(token in lowered_name for token in self.name_tokens):
            return True
        normalized_service_uuids = {str(uuid).lower() for uuid in service_uuids}
        return bool(normalized_service_uuids & self.scan_service_uuids)

    def matches_services(self, name: str, services) -> bool:
        lowered_name = (name or "").lower()
        if "bledom" in lowered_name:
            return False
        service_uuid_set = {str(service.uuid).lower() for service in services}
        characteristic_uuid_set = {
            str(characteristic.uuid).lower()
            for service in services
            for characteristic in service.characteristics
        }
        if TARGET_SERVICE_UUID in service_uuid_set:
            return False
        if "0000ffe1-0000-1000-8000-00805f9b34fb" in characteristic_uuid_set:
            return False
        if any(token in lowered_name for token in self.name_tokens):
            return True
        return bool(
            characteristic_uuid_set & self.known_write_uuids
            or service_uuid_set & self.scan_service_uuids
        )

    def power_payloads(self, enabled: bool) -> list[bytes]:
        return [build_power_command(enabled)]

    def color_payloads(self, red: int, green: int, blue: int) -> list[bytes]:
        return [build_color_command(red, green, blue)]

    def brightness_payloads(self, value_percent: int) -> list[bytes]:
        return [build_brightness_command(value_percent)]

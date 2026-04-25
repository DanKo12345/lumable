from __future__ import annotations

from app.ble_drivers.base import LedBleDriver, clamp, packet, scale_percent_to_byte


BANLANX_V2_TOKENS = (
    "banlanx",
    "sp611e",
    "sp617e",
    "sp620e",
    "sp621e",
)

BANLANX_V3_TOKENS = (
    "banlanx",
    "sp613e",
    "sp614e",
    "sp623e",
    "sp624e",
)

BANLANX_ALL_TOKENS = tuple(dict.fromkeys(BANLANX_V2_TOKENS + BANLANX_V3_TOKENS))
BANLANX_WRITE_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
BANLANX_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"


def _is_v3_name(name: str) -> bool:
    lowered = (name or "").lower()
    return any(token in lowered for token in BANLANX_V3_TOKENS if token != "banlanx")


def build_v2_power_command(enabled: bool) -> bytes:
    return packet(0xA0, 0x62, 0x01, 0x01 if enabled else 0x00)


def build_v2_brightness_command(value_percent: int) -> bytes:
    return packet(0xA0, 0x66, 0x01, scale_percent_to_byte(value_percent))


def build_v2_color_command(red: int, green: int, blue: int, value_percent: int) -> bytes:
    return packet(
        0xA0,
        0x69,
        0x04,
        clamp(red, 0, 255),
        clamp(green, 0, 255),
        clamp(blue, 0, 255),
        scale_percent_to_byte(value_percent),
    )


def build_v3_power_command(enabled: bool) -> bytes:
    return packet(0x0F, 0x01, 0x01 if enabled else 0x00)


def build_v3_brightness_command(value_percent: int) -> bytes:
    return packet(0x12, 0x01, scale_percent_to_byte(value_percent))


def build_v3_color_command(red: int, green: int, blue: int, value_percent: int) -> bytes:
    return packet(
        0x13,
        0x04,
        clamp(red, 0, 255),
        clamp(green, 0, 255),
        clamp(blue, 0, 255),
        scale_percent_to_byte(value_percent),
    )


class BanlanxDriver(LedBleDriver):
    id = "banlanx"
    display_name = "BanlanX"
    name_tokens = BANLANX_ALL_TOKENS
    scan_service_uuids = frozenset()
    known_write_uuids = frozenset({BANLANX_WRITE_UUID})
    interesting_service_uuids = frozenset({BANLANX_SERVICE_UUID})

    def __init__(self) -> None:
        self._last_brightness_percent = 100
        self._variant = "v2"

    def reset_runtime_state(self) -> None:
        self._last_brightness_percent = 100
        self._variant = "v2"

    def remember_brightness(self, value_percent: int) -> None:
        self._last_brightness_percent = clamp(value_percent, 0, 100)

    def matches_scan(self, name: str, service_uuids) -> bool:
        lowered = (name or "").lower()
        return any(token in lowered for token in self.name_tokens)

    def matches_services(self, name: str, services) -> bool:
        lowered = (name or "").lower()
        if not any(token in lowered for token in self.name_tokens):
            return False

        service_uuid_set = {str(service.uuid).lower() for service in services}
        characteristic_uuid_set = {
            str(characteristic.uuid).lower()
            for service in services
            for characteristic in service.characteristics
        }
        if BANLANX_WRITE_UUID not in characteristic_uuid_set:
            return False
        return BANLANX_SERVICE_UUID in service_uuid_set or BANLANX_WRITE_UUID in characteristic_uuid_set

    def _variant_from_name(self, name: str | None) -> str:
        return "v3" if _is_v3_name(name or "") else "v2"

    def configure_for_device(self, name: str | None) -> None:
        self._variant = self._variant_from_name(name)

    def power_payloads(self, enabled: bool) -> list[bytes]:
        if self._variant == "v3":
            return [build_v3_power_command(enabled)]
        return [build_v2_power_command(enabled)]

    def color_payloads(self, red: int, green: int, blue: int) -> list[bytes]:
        if self._variant == "v3":
            return [build_v3_color_command(red, green, blue, self._last_brightness_percent)]
        return [build_v2_color_command(red, green, blue, self._last_brightness_percent)]

    def brightness_payloads(self, value_percent: int) -> list[bytes]:
        self.remember_brightness(value_percent)
        if self._variant == "v3":
            return [build_v3_brightness_command(value_percent)]
        return [build_v2_brightness_command(value_percent)]

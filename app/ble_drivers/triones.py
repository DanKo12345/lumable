from __future__ import annotations

from app.ble_drivers.base import EffectPreset, LedBleDriver, clamp, packet, scale_percent_to_byte
from app.ble_drivers.bledom import TARGET_SERVICE_UUID
from app.ble_drivers.magic_home import MAGIC_HOME_SERVICE_UUID, MAGIC_HOME_WRITE_UUID

MAGIC_HOME_CONFLICT_NAME_TOKENS = (
    "magic home",
    "magichome",
    "magic_home",
    "magic light",
    "magiclight",
    "lednet",
)


def build_power_command(enabled: bool) -> bytes:
    return packet(0xCC, 0x23 if enabled else 0x24, 0x33)


def build_color_command(red: int, green: int, blue: int) -> bytes:
    return packet(0x56, clamp(red, 0, 255), clamp(green, 0, 255), clamp(blue, 0, 255), 0x00, 0xF0, 0xAA)


def build_brightness_command(value_percent: int) -> bytes:
    return packet(0x56, 0x00, 0x00, 0x00, scale_percent_to_byte(value_percent), 0x0F, 0xAA)


def build_effect_command(code: int, speed_byte: int = 0x01) -> bytes:
    return packet(0xBB, clamp(code, 0x25, 0x38), clamp(speed_byte, 0x01, 0xFF), 0x44)


def scale_speed_percent_to_triones_byte(value_percent: int) -> int:
    value_percent = clamp(value_percent, 0, 100)
    return 0xFF - round((value_percent / 100) * (0xFF - 0x01))


TRIONES_EFFECTS: tuple[EffectPreset, ...] = (
    EffectPreset("static_color", 0),
    EffectPreset("triones_rainbow", 0x25),
    EffectPreset("triones_effect_26", 0x26),
    EffectPreset("triones_effect_27", 0x27),
    EffectPreset("triones_effect_28", 0x28),
    EffectPreset("triones_effect_29", 0x29),
    EffectPreset("triones_effect_2a", 0x2A),
    EffectPreset("triones_effect_2b", 0x2B),
    EffectPreset("triones_effect_2c", 0x2C),
    EffectPreset("triones_effect_2d", 0x2D),
    EffectPreset("triones_effect_2e", 0x2E),
    EffectPreset("triones_effect_2f", 0x2F),
    EffectPreset("triones_effect_30", 0x30),
    EffectPreset("triones_effect_31", 0x31),
    EffectPreset("triones_effect_32", 0x32),
    EffectPreset("triones_effect_33", 0x33),
    EffectPreset("triones_effect_34", 0x34),
    EffectPreset("triones_effect_35", 0x35),
    EffectPreset("triones_effect_36", 0x36),
    EffectPreset("triones_effect_37", 0x37),
    EffectPreset("triones_effect_38", 0x38),
)


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
    effects = TRIONES_EFFECTS

    def __init__(self) -> None:
        self._last_brightness_percent = 100

    def reset_runtime_state(self) -> None:
        self._last_brightness_percent = 100

    def remember_brightness(self, value_percent: int) -> None:
        self._last_brightness_percent = clamp(value_percent, 0, 100)

    def matches_scan(self, name: str, service_uuids) -> bool:
        lowered_name = (name or "").lower()
        if any(token in lowered_name for token in MAGIC_HOME_CONFLICT_NAME_TOKENS):
            return False
        if any(token in lowered_name for token in self.name_tokens):
            return True
        normalized_service_uuids = {str(uuid).lower() for uuid in service_uuids}
        return bool(normalized_service_uuids & self.scan_service_uuids)

    def matches_services(self, name: str, services) -> bool:
        lowered_name = (name or "").lower()
        if "bledom" in lowered_name:
            return False
        if any(token in lowered_name for token in MAGIC_HOME_CONFLICT_NAME_TOKENS):
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
        if MAGIC_HOME_SERVICE_UUID in service_uuid_set and MAGIC_HOME_WRITE_UUID in characteristic_uuid_set:
            return False
        return bool(
            characteristic_uuid_set & self.known_write_uuids
            or service_uuid_set & self.scan_service_uuids
        )

    def power_payloads(self, enabled: bool) -> list[bytes]:
        return [build_power_command(enabled)]

    def color_payloads(self, red: int, green: int, blue: int) -> list[bytes]:
        factor = self._last_brightness_percent / 100
        return [
            build_color_command(
                round(clamp(red, 0, 255) * factor),
                round(clamp(green, 0, 255) * factor),
                round(clamp(blue, 0, 255) * factor),
            )
        ]

    def brightness_payloads(self, value_percent: int) -> list[bytes]:
        self.remember_brightness(value_percent)
        # Triones-compatible RGB strips are inconsistent: some accept the
        # standalone brightness command, while others ignore it. Scaling RGB is
        # the reliable path and avoids double-dimming devices that apply both.
        return []

    def effect_payload(self, code: int) -> bytes | None:
        if not 0x25 <= int(code) <= 0x38:
            return None
        return build_effect_command(code)

    def effect_payload_with_speed(self, code: int, value_percent: int) -> bytes | None:
        if not 0x25 <= int(code) <= 0x38:
            return None
        return build_effect_command(code, scale_speed_percent_to_triones_byte(value_percent))

    def supports_effect_speed(self) -> bool:
        return True

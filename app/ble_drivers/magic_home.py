from __future__ import annotations

from app.ble_drivers.base import EffectPreset, LedBleDriver, clamp, packet

MAGIC_HOME_SERVICE_UUID = "0000ffe5-0000-1000-8000-00805f9b34fb"
MAGIC_HOME_WRITE_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"
TRIONES_CONFLICT_NAME_TOKENS = (
    "triones",
    "happy lighting",
    "happylighting",
    "ledble",
    "led blue",
    "ledblue",
    "zengge",
    "magic blue",
)


def build_power_command(enabled: bool) -> bytes:
    return packet(0xCC, 0x23 if enabled else 0x24, 0x33)


def build_color_command(red: int, green: int, blue: int) -> bytes:
    return packet(0x56, clamp(red, 0, 255), clamp(green, 0, 255), clamp(blue, 0, 255), 0x00, 0xF0, 0xAA)


def build_effect_command(code: int) -> bytes:
    return packet(0xBB, 0x00, 0x01, clamp(code, 0x25, 0x38), 0x44)


MAGIC_HOME_EFFECTS: tuple[EffectPreset, ...] = (
    EffectPreset("static_color", 0),
    EffectPreset("magic_home_rainbow", 0x25),
    *(EffectPreset(f"magic_home_effect_{code:02x}", code) for code in range(0x26, 0x39)),
)


class MagicHomeDriver(LedBleDriver):
    id = "magic_home"
    display_name = "Magic Home BLE"
    transport = "BLE"
    protocol_notes = "Bluetooth Magic Home-compatible controller; not the Wi-Fi Magic Home protocol."
    name_tokens = (
        "magic home",
        "magichome",
        "magic_home",
        "magic light",
        "magiclight",
        "lednet",
    )
    scan_service_uuids = frozenset({MAGIC_HOME_SERVICE_UUID})
    known_write_uuids = frozenset({MAGIC_HOME_WRITE_UUID})
    interesting_service_uuids = frozenset({MAGIC_HOME_SERVICE_UUID})
    effects = MAGIC_HOME_EFFECTS

    def __init__(self) -> None:
        self._last_brightness_percent = 100

    def reset_runtime_state(self) -> None:
        self._last_brightness_percent = 100

    def remember_brightness(self, value_percent: int) -> None:
        self._last_brightness_percent = clamp(value_percent, 0, 100)

    def matches_scan(self, name: str, service_uuids) -> bool:
        lowered_name = (name or "").lower()
        if any(token in lowered_name for token in TRIONES_CONFLICT_NAME_TOKENS):
            return False
        # FFE5 is shared by some Triones-family devices. During scan we only
        # claim Magic Home when the advertisement name is explicit; connected
        # service discovery can still validate FFE5 + FFE9 more safely later.
        return any(token in lowered_name for token in self.name_tokens)

    def matches_services(self, name: str, services) -> bool:
        lowered_name = (name or "").lower()
        if any(token in lowered_name for token in TRIONES_CONFLICT_NAME_TOKENS):
            return False

        service_uuid_set = {str(service.uuid).lower() for service in services}
        characteristic_uuid_set = {
            str(characteristic.uuid).lower()
            for service in services
            for characteristic in service.characteristics
        }
        if MAGIC_HOME_SERVICE_UUID in service_uuid_set and MAGIC_HOME_WRITE_UUID in characteristic_uuid_set:
            return True
        return super().matches_services(name, services)

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
        return []

    def effect_payload(self, code: int) -> bytes | None:
        code = int(code)
        if not 0x25 <= code <= 0x38:
            return None
        return build_effect_command(code)

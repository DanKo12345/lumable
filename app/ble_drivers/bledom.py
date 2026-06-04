from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.ble_drivers.base import EffectPreset, LedBleDriver, clamp, normalize_uuid, packet, scale_percent_to_byte

TARGET_SERVICE_UUID = "92053be9-a2b2-d3c5-eab1-15e3cea66b2c"


def build_power_command(enabled: bool) -> bytes:
    if enabled:
        return packet(0x7E, 0x00, 0x04, 0xF0, 0x00, 0x01, 0xFF, 0x00, 0xEF)
    return packet(0x7E, 0x00, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00, 0xEF)


def build_alt_power_command(enabled: bool) -> bytes:
    return packet(0xCC, 0x23 if enabled else 0x24, 0x33)


def build_color_command(red: int, green: int, blue: int) -> bytes:
    return packet(0x7E, 0x00, 0x05, 0x03, clamp(red, 0, 255), clamp(green, 0, 255), clamp(blue, 0, 255), 0x00, 0xEF)


def build_alt_color_command(red: int, green: int, blue: int) -> bytes:
    return packet(0x56, clamp(red, 0, 255), clamp(green, 0, 255), clamp(blue, 0, 255), 0x00, 0xF0, 0xAA)


def build_brightness_command(value: int) -> bytes:
    return packet(0x7E, 0x00, 0x01, clamp(value, 0, 100), 0x00, 0x00, 0x00, 0x00, 0xEF)


def build_alt_brightness_command(value: int) -> bytes:
    return packet(0x56, 0x00, 0x00, 0x00, clamp(value, 0, 255), 0x0F, 0xAA)


def build_speed_command(value: int) -> bytes:
    return packet(0x7E, 0x00, 0x02, clamp(value, 0, 100), 0x00, 0x00, 0x00, 0x00, 0xEF)


BLEDOM_EFFECTS: tuple[EffectPreset, ...] = (
    EffectPreset("static_color", 0),
    EffectPreset("jump_rgb", 0x87),
    EffectPreset("jump_rgb_cmyw", 0x88),
    EffectPreset("fade_spectrum", 0x89),
    EffectPreset("smooth_rainbow", 0x8A),
    EffectPreset("fade_red", 0x8B),
    EffectPreset("fade_green", 0x8C),
    EffectPreset("fade_blue", 0x8D),
    EffectPreset("fade_yellow", 0x8E),
    EffectPreset("fade_cyan", 0x8F),
    EffectPreset("fade_magenta", 0x90),
    EffectPreset("fade_white", 0x91),
    EffectPreset("fade_red_green", 0x92),
    EffectPreset("fade_red_blue", 0x93),
    EffectPreset("fade_green_blue", 0x94),
    EffectPreset("flash_spectrum", 0x95),
    EffectPreset("flash_red", 0x96),
    EffectPreset("flash_green", 0x97),
    EffectPreset("flash_blue", 0x98),
    EffectPreset("flash_yellow", 0x99),
    EffectPreset("flash_cyan", 0x9A),
    EffectPreset("flash_magenta", 0x9B),
    EffectPreset("flash_white", 0x9C),
)

BLEDOM_EFFECT_CODES = frozenset(effect.code for effect in BLEDOM_EFFECTS if effect.code != 0)


def build_effect_command(code: int) -> bytes:
    return packet(0x7E, 0x00, 0x03, int(code), 0x03, 0x00, 0x00, 0x00, 0xEF)

BLEDOM_DETECTION_SERVICE_UUIDS = frozenset(
    {
        TARGET_SERVICE_UUID,
        "0000fff0-0000-1000-8000-00805f9b34fb",
    }
)

BLEDOM_DETECTION_CHARACTERISTIC_UUIDS = frozenset(
    {
        "0000fff3-0000-1000-8000-00805f9b34fb",
        "0000fff4-0000-1000-8000-00805f9b34fb",
        TARGET_SERVICE_UUID,
    }
)


class BledomDriver(LedBleDriver):
    id = "bledom"
    display_name = "BLEDOM"
    name_tokens = ("bledom", "elk-bledom")
    scan_service_uuids = frozenset({TARGET_SERVICE_UUID})
    known_write_uuids = frozenset(
        {
            "0000fff3-0000-1000-8000-00805f9b34fb",
            "0000fff4-0000-1000-8000-00805f9b34fb",
            "0000ffd9-0000-1000-8000-00805f9b34fb",
            "0000fff0-0000-1000-8000-00805f9b34fb",
            "0000ffe1-0000-1000-8000-00805f9b34fb",
            "0000ffe2-0000-1000-8000-00805f9b34fb",
            "0000ffe9-0000-1000-8000-00805f9b34fb",
            TARGET_SERVICE_UUID,
        }
    )
    interesting_service_uuids = frozenset(
        {
            TARGET_SERVICE_UUID,
            "0000fff0-0000-1000-8000-00805f9b34fb",
            "0000ffe0-0000-1000-8000-00805f9b34fb",
        }
    )
    effects = BLEDOM_EFFECTS

    def __init__(self) -> None:
        self._working_variants: dict[str, str] = {}

    def reset_runtime_state(self) -> None:
        self._working_variants = {}

    def remember_working_payload(self, payload: bytes) -> None:
        if not payload:
            return
        kind = self._payload_kind(payload)
        if kind is None:
            return
        if payload[0] == 0x7E:
            self._working_variants[kind] = "primary"
        elif payload[0] in {0xCC, 0x56}:
            self._working_variants[kind] = "alt"

    def _variant_payloads(self, kind: str, primary: bytes, alternate: bytes, *, prefer_alt_first: bool = False) -> list[bytes]:
        variant = self._working_variants.get(kind)
        if variant == "primary":
            return [primary]
        if variant == "alt":
            return [alternate]
        if prefer_alt_first:
            return [alternate, primary]
        return [primary, alternate]

    @staticmethod
    def _payload_kind(payload: bytes) -> str | None:
        if len(payload) >= 9 and payload[0] == 0x7E:
            command = payload[2]
            if command == 0x04:
                return "power"
            if command == 0x05:
                return "color"
            if command == 0x01:
                return "brightness"
        if len(payload) == 3 and payload[0] == 0xCC:
            return "power"
        if len(payload) == 7 and payload[0] == 0x56:
            if payload[1:4] == b"\x00\x00\x00" and payload[5:] == b"\x0f\xaa":
                return "brightness"
            return "color"
        return None

    def matches_scan(self, name: str, service_uuids: Iterable[str]) -> bool:
        lowered_name = (name or "").lower()
        normalized_service_uuids = {normalize_uuid(uuid) for uuid in service_uuids}
        if any(token in lowered_name for token in self.name_tokens):
            return True
        return bool(normalized_service_uuids & BLEDOM_DETECTION_SERVICE_UUIDS)

    def matches_services(self, name: str, services: Iterable[Any]) -> bool:
        lowered_name = (name or "").lower()
        if any(token in lowered_name for token in self.name_tokens):
            return True

        service_uuid_set: set[str] = set()
        characteristic_uuid_set: set[str] = set()
        for service in services:
            service_uuid_set.add(normalize_uuid(service.uuid))
            for characteristic in service.characteristics:
                characteristic_uuid_set.add(normalize_uuid(characteristic.uuid))

        return bool(
            service_uuid_set & BLEDOM_DETECTION_SERVICE_UUIDS
            or characteristic_uuid_set & BLEDOM_DETECTION_CHARACTERISTIC_UUIDS
        )

    def power_payloads(self, enabled: bool) -> list[bytes]:
        return self._variant_payloads("power", build_power_command(enabled), build_alt_power_command(enabled))

    def color_payloads(self, red: int, green: int, blue: int) -> list[bytes]:
        return self._variant_payloads("color", build_color_command(red, green, blue), build_alt_color_command(red, green, blue))

    def brightness_payloads(self, value_percent: int) -> list[bytes]:
        return self._variant_payloads(
            "brightness",
            build_brightness_command(value_percent),
            build_alt_brightness_command(scale_percent_to_byte(value_percent)),
        )

    def effect_payload(self, code: int) -> bytes | None:
        if int(code) not in BLEDOM_EFFECT_CODES:
            return None
        return build_effect_command(code)

    def speed_payload(self, value_percent: int) -> bytes | None:
        return build_speed_command(value_percent)

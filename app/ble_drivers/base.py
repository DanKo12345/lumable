from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from bleak.backends.characteristic import BleakGATTCharacteristic


def normalize_uuid(value: Any) -> str:
    return str(value).lower()


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def packet(*values: int) -> bytes:
    return bytes(values)


def scale_percent_to_byte(value: int) -> int:
    value = clamp(value, 0, 100)
    return round((value / 100) * 255)


@dataclass(slots=True, frozen=True)
class EffectPreset:
    key: str
    code: int


class LedBleDriver:
    id = "generic"
    display_name = "Generic BLE LED"
    transport = "BLE"
    protocol_notes = ""
    name_tokens: tuple[str, ...] = ()
    scan_service_uuids: frozenset[str] = frozenset()
    known_write_uuids: frozenset[str] = frozenset()
    interesting_service_uuids: frozenset[str] = frozenset()
    effects: tuple[EffectPreset, ...] = ()

    def reset_runtime_state(self) -> None:
        return None

    def remember_brightness(self, value_percent: int) -> None:
        return None

    def matches_scan(self, name: str, service_uuids: Iterable[str]) -> bool:
        lowered_name = (name or "").lower()
        normalized_service_uuids = {normalize_uuid(uuid) for uuid in service_uuids}
        return bool(
            any(token in lowered_name for token in self.name_tokens)
            or normalized_service_uuids & (self.scan_service_uuids | self.interesting_service_uuids)
        )

    def matches_services(self, name: str, services: Iterable[Any]) -> bool:
        lowered_name = (name or "").lower()
        service_uuid_set: set[str] = set()
        characteristic_uuid_set: set[str] = set()

        for service in services:
            service_uuid = normalize_uuid(service.uuid)
            service_uuid_set.add(service_uuid)
            for characteristic in service.characteristics:
                characteristic_uuid_set.add(normalize_uuid(characteristic.uuid))

        if any(token in lowered_name for token in self.name_tokens):
            return True
        known = self.scan_service_uuids | self.interesting_service_uuids | self.known_write_uuids
        return bool(service_uuid_set & known or characteristic_uuid_set & known)

    def pick_write_characteristic(self, services: Iterable[Any]) -> BleakGATTCharacteristic | None:
        exact_match = None
        service_match = None
        generic_write = None
        known_uuid_match = None

        for service in services:
            service_uuid = normalize_uuid(service.uuid)
            for characteristic in service.characteristics:
                properties = {prop.lower() for prop in characteristic.properties}
                char_uuid = normalize_uuid(characteristic.uuid)
                looks_writable = bool({"write", "write-without-response"} & properties)

                if looks_writable and char_uuid in self.known_write_uuids and known_uuid_match is None:
                    known_uuid_match = characteristic

                if not looks_writable:
                    continue

                if char_uuid in self.known_write_uuids:
                    exact_match = characteristic
                elif service_uuid in self.interesting_service_uuids and service_match is None:
                    service_match = characteristic
                elif generic_write is None:
                    generic_write = characteristic

        return exact_match or known_uuid_match or service_match or generic_write

    def collect_write_characteristics(self, services: Iterable[Any]) -> list[BleakGATTCharacteristic]:
        candidates: list[BleakGATTCharacteristic] = []
        seen: set[str] = set()

        for service in services:
            for characteristic in service.characteristics:
                char_uuid = normalize_uuid(characteristic.uuid)
                properties = {prop.lower() for prop in characteristic.properties}
                looks_writable = bool({"write", "write-without-response"} & properties)
                if not looks_writable:
                    continue
                if char_uuid in seen:
                    continue
                candidates.append(characteristic)
                seen.add(char_uuid)

        return candidates

    def power_payloads(self, enabled: bool) -> list[bytes]:
        raise NotImplementedError

    def color_payloads(self, red: int, green: int, blue: int) -> list[bytes]:
        raise NotImplementedError

    def brightness_payloads(self, value_percent: int) -> list[bytes]:
        raise NotImplementedError

    def supports_brightness(self) -> bool:
        """Whether this driver has a brightness command, asked without using it.

        Answering by calling ``brightness_payloads`` would be a side effect:
        several drivers remember the value they were handed and use it for the
        next colour write. Drawing the device card must not decide how bright
        the next command turns out.
        """
        return type(self).brightness_payloads is not LedBleDriver.brightness_payloads

    def effect_payload(self, code: int) -> bytes | None:
        return None

    def effect_payload_with_speed(self, code: int, value_percent: int) -> bytes | None:
        return self.effect_payload(code)

    def speed_payload(self, value_percent: int) -> bytes | None:
        return None

    def supports_effect_speed(self) -> bool:
        return self.speed_payload(50) is not None

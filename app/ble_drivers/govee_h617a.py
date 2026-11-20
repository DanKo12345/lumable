from __future__ import annotations

import re
from collections.abc import Iterable
from functools import reduce
from operator import xor
from typing import Any

from bleak.backends.characteristic import BleakGATTCharacteristic

from app.ble_drivers.base import EffectPreset, EffectSequence, LedBleDriver, clamp, normalize_uuid
from app.ble_drivers.govee_h617a_scenes import SCENE_RECORDINGS

GOVEE_CONTROL_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"
_H617A_NAME = re.compile(r"govee[_ -]h617a(?:[_ -][a-z0-9]+)?", re.IGNORECASE)
_SCENE_PACKET_HEX_LENGTH = 40
_SCENE_PACKET_INTERVAL_SECONDS = 0.05


def _scene_sequence(recording: str) -> EffectSequence:
    frames = tuple(
        bytes.fromhex(recording[offset : offset + _SCENE_PACKET_HEX_LENGTH])
        for offset in range(0, len(recording), _SCENE_PACKET_HEX_LENGTH)
    )
    return EffectSequence(frames, _SCENE_PACKET_INTERVAL_SECONDS)


_SCENE_SEQUENCES = {code: _scene_sequence(recording) for code, _, recording in SCENE_RECORDINGS}


def _command(code: int, *data: int) -> bytes:
    frame = bytes((0x33, code, *data)).ljust(19, b"\x00")
    return frame + bytes((reduce(xor, frame),))


class GoveeH617ADriver(LedBleDriver):
    id = "govee_h617a"
    display_name = "Govee H617A"
    protocol_notes = "H617A only; whole-strip RGB and a captured scene catalog over Bluetooth."
    known_write_uuids = frozenset({GOVEE_CONTROL_UUID})
    allow_protocol_guess = False
    minimum_brightness_percent = 1
    effects = (EffectPreset("static_color", 0), *(EffectPreset(key, code) for code, key, _ in SCENE_RECORDINGS))

    def matches_scan(self, name: str, service_uuids: Iterable[str]) -> bool:
        # Govee models share the control UUID, but not all use these packets.
        return _H617A_NAME.fullmatch((name or "").strip()) is not None

    def matches_services(self, name: str, services: Iterable[Any]) -> bool:
        return self.matches_scan(name, ()) and self.pick_write_characteristic(services) is not None

    def pick_write_characteristic(self, services: Iterable[Any]) -> BleakGATTCharacteristic | None:
        for service in services:
            for characteristic in service.characteristics:
                if normalize_uuid(characteristic.uuid) != GOVEE_CONTROL_UUID:
                    continue
                if any(prop.lower() == "write-without-response" for prop in characteristic.properties):
                    return characteristic
        return None

    def collect_write_characteristics(self, services: Iterable[Any]) -> list[BleakGATTCharacteristic]:
        characteristic = self.pick_write_characteristic(services)
        return [characteristic] if characteristic is not None else []

    def power_payloads(self, enabled: bool) -> list[bytes]:
        return [_command(0x01, int(enabled))]

    def brightness_payloads(self, value_percent: int) -> list[bytes]:
        # This model uses 1-100, with off as a separate power command.
        return [_command(0x04, clamp(value_percent, self.minimum_brightness_percent, 100))]

    def color_payloads(self, red: int, green: int, blue: int) -> list[bytes]:
        rgb = (clamp(channel, 0, 255) for channel in (red, green, blue))
        # Mode 0x15 with a 0x7fff mask paints the entire strip.
        return [_command(0x05, 0x15, 0x01, *rgb, 0, 0, 0, 0, 0, 0xFF, 0x7F)]

    def effect_sequence(self, code: int) -> EffectSequence | None:
        return _SCENE_SEQUENCES.get(code)

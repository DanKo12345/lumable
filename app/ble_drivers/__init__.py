from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.ble_drivers.banlanx import BanlanxDriver
from app.ble_drivers.base import EffectPreset, LedBleDriver, normalize_uuid
from app.ble_drivers.bledom import BLEDOM_EFFECTS, BledomDriver
from app.ble_drivers.magic_home import MagicHomeDriver
from app.ble_drivers.triones import TrionesDriver
from app.protocol_probe import DeviceProfile, DriverProfile, ProbeCandidate, rank_candidates

_DRIVER_INSTANCES: tuple[LedBleDriver, ...] = (
    BledomDriver(),
    BanlanxDriver(),
    MagicHomeDriver(),
    TrionesDriver(),
)

DRIVERS: tuple[LedBleDriver, ...] = _DRIVER_INSTANCES
DRIVER_BY_ID: dict[str, LedBleDriver] = {driver.id: driver for driver in DRIVERS}
EFFECTS: list[EffectPreset] = list(BLEDOM_EFFECTS)


def get_driver_by_id(driver_id: str | None) -> LedBleDriver | None:
    if not driver_id:
        return None
    return DRIVER_BY_ID.get(driver_id)


def detect_scan_driver(name: str, service_uuids: Iterable[str]) -> LedBleDriver | None:
    normalized_service_uuids = {normalize_uuid(uuid) for uuid in service_uuids}
    for driver in DRIVERS:
        if driver.matches_scan(name, normalized_service_uuids):
            return driver
    return None


def _driver_profiles() -> list[DriverProfile]:
    def norm(uuids: Iterable[str]) -> frozenset[str]:
        return frozenset(normalize_uuid(uuid) for uuid in uuids)

    return [
        DriverProfile(
            id=driver.id,
            display_name=driver.display_name,
            name_tokens=tuple(driver.name_tokens),
            scan_service_uuids=norm(driver.scan_service_uuids),
            interesting_service_uuids=norm(driver.interesting_service_uuids),
            known_write_uuids=norm(driver.known_write_uuids),
        )
        for driver in DRIVERS
    ]


def device_profile_from_services(name: str, services: Iterable[Any]) -> DeviceProfile:
    service_uuids: set[str] = set()
    char_uuids: set[str] = set()
    writable_char_uuids: set[str] = set()
    for service in services:
        service_uuids.add(normalize_uuid(service.uuid))
        for characteristic in service.characteristics:
            char_uuid = normalize_uuid(characteristic.uuid)
            char_uuids.add(char_uuid)
            properties = {prop.lower() for prop in characteristic.properties}
            if {"write", "write-without-response"} & properties:
                writable_char_uuids.add(char_uuid)
    return DeviceProfile(
        name=name or "",
        service_uuids=frozenset(service_uuids),
        char_uuids=frozenset(char_uuids),
        writable_char_uuids=frozenset(writable_char_uuids),
    )


def probe_driver_candidates(name: str, services: Iterable[Any]) -> list[ProbeCandidate]:
    """Ranked driver guesses for an unrecognised controller, from GATT
    inspection only (no writes). Empty when nothing is a confident-enough guess."""
    from app.protocol_probe import OFFER_THRESHOLD

    return rank_candidates(
        _driver_profiles(),
        device_profile_from_services(name, services),
        min_score=OFFER_THRESHOLD,
    )


def detect_connected_driver(name: str, services: Iterable[Any], preferred_id: str | None = None) -> LedBleDriver | None:
    preferred = get_driver_by_id(preferred_id)
    if preferred is not None and preferred.matches_services(name, services):
        return preferred
    for driver in DRIVERS:
        if driver is preferred:
            continue
        if driver.matches_services(name, services):
            return driver
    return None

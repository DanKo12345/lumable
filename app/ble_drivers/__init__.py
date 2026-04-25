from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.ble_drivers.base import EffectPreset, LedBleDriver, normalize_uuid
from app.ble_drivers.banlanx import BanlanxDriver
from app.ble_drivers.bledom import BLEDOM_EFFECTS, BledomDriver
from app.ble_drivers.triones import TrionesDriver


_DRIVER_INSTANCES: tuple[LedBleDriver, ...] = (
    BledomDriver(),
    BanlanxDriver(),
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

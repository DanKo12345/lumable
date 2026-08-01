"""Recorded BLE advertisements, so a driver can be developed without the device.

Adding support for a controller normally needs the controller: you scan, you
guess, you flash a build, you ask the owner to try again. A snapshot breaks that
loop — the owner sends one file, and from then on detection can be written and
tested against exactly what their strip broadcasts.

The format is deliberately dull: plain JSON, hex strings, no pickling, nothing
that depends on the bleak version that captured it. It has to still be readable
when someone opens an issue from a year ago.

Addresses are masked on export. A BLE address identifies a person's hardware and
these files end up attached to public issues; the last octets are all a driver
needs to tell two strips apart in the same capture.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

SNAPSHOT_VERSION = "scan.v1"

# Kept out of the exported file: enough to distinguish devices within one
# capture, not enough to identify the hardware afterwards.
_MASK = "…"


def mask_address(address: str) -> str:
    """"AA:BB:CC:DD:EE:FF" -> "…:EE:FF".

    Idempotent: a snapshot that is loaded and exported again must keep the same
    two octets rather than lose one more on every pass.
    """
    text = str(address or "").strip()
    if text.startswith(_MASK):
        return text
    parts = re.split(r"[:-]", text)
    if len(parts) < 3:
        return text  # not an address shape we recognise; leave it alone
    return _MASK + ":" + ":".join(parts[-2:])


def _hex(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value or "")


def _clean_uuid(value: Any) -> str:
    return str(value or "").strip().lower()


@dataclass(frozen=True)
class AdvertisementRecord:
    """One device as it appeared in one scan."""

    name: str = ""
    address: str = ""
    rssi: int | None = None
    service_uuids: tuple[str, ...] = ()
    # Company identifier -> payload as hex. The single most telling field for
    # working out which family a controller belongs to.
    manufacturer_data: dict[int, str] = field(default_factory=dict)
    service_data: dict[str, str] = field(default_factory=dict)
    tx_power: int | None = None

    def masked(self) -> AdvertisementRecord:
        return AdvertisementRecord(
            name=self.name,
            address=mask_address(self.address),
            rssi=self.rssi,
            service_uuids=self.service_uuids,
            manufacturer_data=dict(self.manufacturer_data),
            service_data=dict(self.service_data),
            tx_power=self.tx_power,
        )


@dataclass(frozen=True)
class ScanSnapshot:
    records: tuple[AdvertisementRecord, ...] = ()
    # Read-only GATT inspections the user asked for, if any.
    inspections: tuple[Any, ...] = ()
    captured_at: str = ""
    app_version: str = ""
    note: str = ""
    version: str = SNAPSHOT_VERSION


def record_from_advertisement(device: Any, advertisement: Any) -> AdvertisementRecord:
    """Build a record from whatever the scanner handed us.

    Everything is read defensively: bleak's advertisement object has gained and
    lost attributes across versions, and a snapshot that raises on capture is
    worth nothing to the person trying to report their device.
    """
    name = (
        getattr(device, "name", None)
        or getattr(advertisement, "local_name", None)
        or ""
    )
    raw_manufacturer = getattr(advertisement, "manufacturer_data", None) or {}
    manufacturer: dict[int, str] = {}
    for company, payload in dict(raw_manufacturer).items():
        try:
            manufacturer[int(company)] = _hex(payload)
        except (TypeError, ValueError):
            continue

    raw_service_data = getattr(advertisement, "service_data", None) or {}
    service_data = {_clean_uuid(uuid): _hex(payload) for uuid, payload in dict(raw_service_data).items()}

    rssi = getattr(advertisement, "rssi", None)
    return AdvertisementRecord(
        name=str(name),
        address=str(getattr(device, "address", "") or ""),
        rssi=int(rssi) if isinstance(rssi, int) else None,
        service_uuids=tuple(_clean_uuid(uuid) for uuid in (getattr(advertisement, "service_uuids", None) or [])),
        manufacturer_data=manufacturer,
        service_data=service_data,
        tx_power=getattr(advertisement, "tx_power", None),
    )


def snapshot_to_dict(snapshot: ScanSnapshot, *, mask: bool = True) -> dict[str, Any]:
    """Serialise for a file the user can attach to an issue."""
    records = [record.masked() if mask else record for record in snapshot.records]
    return {
        "version": SNAPSHOT_VERSION,
        "captured_at": snapshot.captured_at or datetime.now().isoformat(timespec="seconds"),
        "app_version": snapshot.app_version,
        "note": snapshot.note,
        "inspections": [inspection_to_dict(item, mask=mask) for item in snapshot.inspections],
        "records": [
            {
                "name": record.name,
                "address": record.address,
                "rssi": record.rssi,
                "service_uuids": list(record.service_uuids),
                # Company ids are JSON object keys, so they travel as strings and
                # come back as ints on load.
                "manufacturer_data": {str(company): payload for company, payload in record.manufacturer_data.items()},
                "service_data": dict(record.service_data),
                "tx_power": record.tx_power,
            }
            for record in records
        ],
    }


def snapshot_from_dict(data: Any) -> ScanSnapshot:
    """Read a snapshot. Unreadable entries are dropped, never raised.

    These files are hand-edited and pasted into issues, so one mangled record
    must not cost the rest of the capture.
    """
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        return ScanSnapshot()
    records: list[AdvertisementRecord] = []
    for item in data["records"]:
        record = _record_from_dict(item)
        if record is not None:
            records.append(record)
    inspections = [
        inspection
        for inspection in (inspection_from_dict(item) for item in (data.get("inspections") or []))
        if inspection is not None
    ]
    return ScanSnapshot(
        records=tuple(records),
        inspections=tuple(inspections),
        captured_at=str(data.get("captured_at", "")),
        app_version=str(data.get("app_version", "")),
        note=str(data.get("note", "")),
        version=str(data.get("version", SNAPSHOT_VERSION)),
    )


def _record_from_dict(item: Any) -> AdvertisementRecord | None:
    if not isinstance(item, dict):
        return None
    manufacturer: dict[int, str] = {}
    for company, payload in dict(item.get("manufacturer_data") or {}).items():
        try:
            manufacturer[int(company)] = str(payload or "")
        except (TypeError, ValueError):
            continue
    service_uuids = item.get("service_uuids")
    service_data = item.get("service_data")
    return AdvertisementRecord(
        name=str(item.get("name", "")),
        address=str(item.get("address", "")),
        rssi=item.get("rssi") if isinstance(item.get("rssi"), int) else None,
        service_uuids=tuple(_clean_uuid(uuid) for uuid in service_uuids) if isinstance(service_uuids, list) else (),
        manufacturer_data=manufacturer,
        service_data={_clean_uuid(k): str(v or "") for k, v in dict(service_data).items()}
        if isinstance(service_data, dict)
        else {},
        tx_power=item.get("tx_power") if isinstance(item.get("tx_power"), int) else None,
    )


def replay(snapshot: ScanSnapshot, detect) -> list[tuple[AdvertisementRecord, str]]:
    """Run detection over a recorded scan.

    ``detect(name, service_uuids)`` is the real scan-time matcher, so a test
    asserts what the shipped app would have decided — not what a copy of the
    logic in the test would.

    Returns one pair per record: the record and the driver id it matched, or an
    empty string for "no driver claimed this".
    """
    outcome: list[tuple[AdvertisementRecord, str]] = []
    for record in snapshot.records:
        driver = detect(record.name, list(record.service_uuids))
        outcome.append((record, getattr(driver, "id", "") if driver is not None else ""))
    return outcome


def save_snapshot(path, snapshot: ScanSnapshot, *, note: str = "") -> bool:
    """Write a snapshot for the user to attach to an issue. False on failure.

    Never raises: this is invoked from a button in diagnostics, and a full disk
    or a read-only folder should show a message, not take the app down.
    """
    target = Path(path)
    payload = snapshot_to_dict(
        ScanSnapshot(
            records=snapshot.records,
            captured_at=snapshot.captured_at,
            app_version=snapshot.app_version,
            note=note or snapshot.note,
        )
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        return False
    return True


# What the diagnostics card should say about the last capture. Codes, not text:
# the wording is localised at display time like everything else.
STATE_NO_SNAPSHOT = "no_snapshot"  # nothing scanned yet this session
STATE_EMPTY = "empty"  # the scan ran and saw nothing at all
STATE_UNSUPPORTED = "unsupported"  # devices were seen that no driver claims
STATE_ALL_SUPPORTED = "all_supported"  # everything seen is already handled


def snapshot_state(snapshot: ScanSnapshot, unsupported_count: int) -> str:
    """Which of the four situations the last scan left us in.

    Pure so the wording and the reasoning can be tested apart from Qt. The
    unsupported count comes from the caller because "no driver claimed it" is a
    detection question, not something the raw capture knows.
    """
    if not snapshot.captured_at and not snapshot.records:
        return STATE_NO_SNAPSHOT
    if not snapshot.records:
        return STATE_EMPTY
    return STATE_UNSUPPORTED if unsupported_count > 0 else STATE_ALL_SUPPORTED


def is_possible_controller(record: AdvertisementRecord) -> bool:
    """Worth offering as an unrecognised controller.

    Two rules, both about what the user can act on:

    * A device with neither a name nor a service UUID gives them nothing to
      recognise it by, and there are a lot of those in any block of flats. It
      stays out of the list — but never out of the snapshot.
    * Anything with a name or advertised services is shown, even if it is
      plainly somebody's laptop. Hiding a controller is the expensive mistake;
      a named device the user can dismiss at a glance is the cheap one.

    Manufacturer id is deliberately not used either way: chips and identifiers
    are shared across unrelated products, so it proves nothing in both
    directions.
    """
    return bool(record.name.strip()) or bool(record.service_uuids)


def sort_for_display(records):
    """Closest first. Signal strength orders the list and nothing more — it is
    not evidence that a device is compatible."""
    return sorted(
        records,
        key=lambda record: (record.rssi is None, -(record.rssi or 0)),
    )


@dataclass(frozen=True)
class GattCharacteristic:
    uuid: str
    properties: tuple[str, ...] = ()


@dataclass(frozen=True)
class GattService:
    uuid: str
    characteristics: tuple[GattCharacteristic, ...] = ()


@dataclass(frozen=True)
class GattInspection:
    """What one device exposes, read and nothing more.

    Produced by connecting, listing services and disconnecting. No payload is
    ever written, no driver is guessed, and the strip's state is left exactly as
    it was — the point is to learn what a controller offers, not to try it.
    """

    address: str = ""
    name: str = ""
    services: tuple[GattService, ...] = ()
    error: str = ""
    # Identifies the request this answers. A rescan or a closing window makes an
    # in-flight check irrelevant, and its late result must be recognisable.
    token: int = 0


def inspection_to_dict(inspection: GattInspection, *, mask: bool = True) -> dict[str, Any]:
    return {
        "address": mask_address(inspection.address) if mask else inspection.address,
        "name": inspection.name,
        "error": inspection.error,
        "services": [
            {
                "uuid": service.uuid,
                "characteristics": [
                    {"uuid": characteristic.uuid, "properties": list(characteristic.properties)}
                    for characteristic in service.characteristics
                ],
            }
            for service in inspection.services
        ],
    }


def inspection_from_dict(data: Any) -> GattInspection | None:
    if not isinstance(data, dict):
        return None
    services: list[GattService] = []
    for raw_service in data.get("services") or []:
        if not isinstance(raw_service, dict):
            continue
        characteristics: list[GattCharacteristic] = []
        for raw_characteristic in raw_service.get("characteristics") or []:
            if not isinstance(raw_characteristic, dict):
                continue
            properties = raw_characteristic.get("properties")
            characteristics.append(
                GattCharacteristic(
                    uuid=_clean_uuid(raw_characteristic.get("uuid")),
                    properties=tuple(str(item) for item in properties) if isinstance(properties, list) else (),
                )
            )
        services.append(
            GattService(uuid=_clean_uuid(raw_service.get("uuid")), characteristics=tuple(characteristics))
        )
    return GattInspection(
        address=str(data.get("address", "")),
        name=str(data.get("name", "")),
        services=tuple(services),
        error=str(data.get("error", "")),
    )

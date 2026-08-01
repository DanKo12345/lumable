"""Scan snapshots: capture, survive a round trip, and drive real detection.

The point of the format is that someone can report a controller once and every
later change to detection can be checked against it — so the tests here are
about what a maintainer can still do a year after the capture.
"""

from __future__ import annotations

import json

from app.ble_drivers import detect_scan_driver
from app.scan_snapshot import (
    SNAPSHOT_VERSION,
    AdvertisementRecord,
    ScanSnapshot,
    mask_address,
    record_from_advertisement,
    replay,
    snapshot_from_dict,
    snapshot_to_dict,
)


class _Device:
    def __init__(self, name, address):
        self.name = name
        self.address = address


class _Advertisement:
    def __init__(self, **kwargs):
        self.local_name = kwargs.get("local_name")
        self.rssi = kwargs.get("rssi", -60)
        self.service_uuids = kwargs.get("service_uuids", [])
        self.manufacturer_data = kwargs.get("manufacturer_data", {})
        self.service_data = kwargs.get("service_data", {})
        self.tx_power = kwargs.get("tx_power")


def test_a_capture_keeps_the_manufacturer_data() -> None:
    """The single most telling field for working out a controller's family, and
    the one the scan did not record before."""
    record = record_from_advertisement(
        _Device("SP630E", "AA:BB:CC:DD:EE:FF"),
        _Advertisement(
            service_uuids=["0000FFF0-0000-1000-8000-00805F9B34FB"],
            manufacturer_data={0x5A54: b"\x01\x02\x03"},
            service_data={"0000FFF0-0000-1000-8000-00805F9B34FB": b"\xaa"},
            tx_power=4,
        ),
    )

    assert record.name == "SP630E"
    assert record.manufacturer_data == {0x5A54: "010203"}
    assert record.service_data == {"0000fff0-0000-1000-8000-00805f9b34fb": "aa"}
    assert record.service_uuids == ("0000fff0-0000-1000-8000-00805f9b34fb",)
    assert record.tx_power == 4


def test_a_capture_survives_a_scanner_that_lost_some_attributes() -> None:
    """bleak has gained and lost advertisement fields across versions. A capture
    that raises is worth nothing to the person trying to report their device."""

    class _Sparse:
        rssi = None

    record = record_from_advertisement(_Device(None, "AA:BB"), _Sparse())

    assert record.name == ""
    assert record.manufacturer_data == {}
    assert record.service_uuids == ()
    assert record.rssi is None


def test_the_local_name_is_used_when_the_device_has_none() -> None:
    record = record_from_advertisement(
        _Device(None, "AA:BB"), _Advertisement(local_name="SP630E")
    )

    assert record.name == "SP630E"


def test_an_exported_snapshot_hides_the_address() -> None:
    """These files get attached to public issues; a BLE address identifies a
    person's hardware."""
    snapshot = ScanSnapshot(
        records=(AdvertisementRecord(name="SP630E", address="AA:BB:CC:DD:EE:FF"),)
    )

    exported = snapshot_to_dict(snapshot)

    assert exported["records"][0]["address"] == "…:EE:FF"
    assert "AA:BB:CC" not in json.dumps(exported)


def test_masking_still_tells_two_strips_apart() -> None:
    assert mask_address("AA:BB:CC:DD:EE:01") != mask_address("AA:BB:CC:DD:EE:02")


def test_a_snapshot_survives_a_round_trip_through_a_file() -> None:
    snapshot = ScanSnapshot(
        records=(
            AdvertisementRecord(
                name="SP630E",
                address="…:EE:FF",
                rssi=-55,
                service_uuids=("0000fff0-0000-1000-8000-00805f9b34fb",),
                manufacturer_data={0x5A54: "010203"},
                service_data={"0000fff0": "aa"},
                tx_power=4,
            ),
        ),
        captured_at="2026-08-01T12:00:00",
        app_version="0.3.7",
        note="issue #2",
    )

    reloaded = snapshot_from_dict(json.loads(json.dumps(snapshot_to_dict(snapshot))))

    assert reloaded.records == snapshot.records
    assert reloaded.app_version == "0.3.7"
    assert reloaded.note == "issue #2"
    assert reloaded.version == SNAPSHOT_VERSION


def test_company_ids_come_back_as_numbers() -> None:
    """They travel as JSON object keys, which are always strings."""
    snapshot = ScanSnapshot(
        records=(AdvertisementRecord(name="x", manufacturer_data={0x5A54: "01"}),)
    )

    reloaded = snapshot_from_dict(json.loads(json.dumps(snapshot_to_dict(snapshot))))

    assert reloaded.records[0].manufacturer_data == {0x5A54: "01"}


def test_one_mangled_record_does_not_cost_the_capture() -> None:
    """Snapshots are hand-edited and pasted into issues."""
    reloaded = snapshot_from_dict(
        {
            "records": [
                {"name": "good", "service_uuids": ["0000fff0"]},
                "nonsense",
                {"name": "also good", "manufacturer_data": {"not-a-number": "01"}},
            ]
        }
    )

    assert [record.name for record in reloaded.records] == ["good", "also good"]
    assert reloaded.records[1].manufacturer_data == {}


def test_a_file_that_is_not_a_snapshot_reads_as_empty() -> None:
    assert snapshot_from_dict({"hello": "world"}).records == ()
    assert snapshot_from_dict(None).records == ()


def test_replay_runs_the_real_detection_over_a_capture() -> None:
    """The assertion is about what the shipped app decides, not about a copy of
    the matching logic living in the test."""
    snapshot = ScanSnapshot(
        records=(
            AdvertisementRecord(name="ELK-BLEDOM", service_uuids=("0000fff0-0000-1000-8000-00805f9b34fb",)),
            AdvertisementRecord(name="Some Fridge", service_uuids=("0000180a-0000-1000-8000-00805f9b34fb",)),
        )
    )

    outcome = replay(snapshot, detect_scan_driver)

    assert [driver_id for _, driver_id in outcome] == ["bledom", ""]


def test_replay_reports_an_unclaimed_device_as_an_empty_driver() -> None:
    """The case the SP630E report is: nothing matched, and that has to be
    visible rather than look like a crash."""
    snapshot = ScanSnapshot(records=(AdvertisementRecord(name="SP630E"),))

    (record, driver_id), = replay(snapshot, detect_scan_driver)

    assert record.name == "SP630E"
    assert driver_id == ""


def test_masking_an_already_masked_address_changes_nothing() -> None:
    """A snapshot that is loaded and exported again must keep the same two
    octets, not lose one more on every pass."""
    once = mask_address("AA:BB:CC:DD:EE:FF")

    assert once == "…:EE:FF"
    assert mask_address(once) == once
    assert mask_address(mask_address(once)) == once


def test_an_address_that_is_not_an_address_is_left_alone() -> None:
    assert mask_address("") == ""
    assert mask_address("localhost") == "localhost"


def test_the_card_can_tell_the_four_situations_apart() -> None:
    """"Nothing scanned yet" and "scanned, found nothing" look the same in the
    data but mean opposite things to the person reading the card."""
    from app.scan_snapshot import (
        STATE_ALL_SUPPORTED,
        STATE_EMPTY,
        STATE_NO_SNAPSHOT,
        STATE_UNSUPPORTED,
        snapshot_state,
    )

    assert snapshot_state(ScanSnapshot(), 0) == STATE_NO_SNAPSHOT
    assert snapshot_state(ScanSnapshot(captured_at="2026-08-01T12:00:00"), 0) == STATE_EMPTY

    seen = ScanSnapshot(
        records=(AdvertisementRecord(name="SP630E"),), captured_at="2026-08-01T12:00:00"
    )
    assert snapshot_state(seen, 1) == STATE_UNSUPPORTED
    assert snapshot_state(seen, 0) == STATE_ALL_SUPPORTED

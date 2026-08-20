"""Capturing a scan: what ends up in the snapshot, and what a capture may cost.

Scanning is the one thing that must keep working. Everything here is really
about that: recording is bookkeeping, and bookkeeping never gets to break the
feature it is recording.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.app_info import APP_VERSION
from app.ble import (
    BleController,
    _strongest_signal_first,
)
from app.scan_snapshot import SNAPSHOT_VERSION, ScanSnapshot, save_snapshot, snapshot_from_dict


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


@pytest.fixture()
def controller():
    ble = BleController()
    try:
        yield ble
    finally:
        ble.shutdown()


def _run_scan(ble, monkeypatch, found: dict) -> None:
    """Drive the real _scan() with a stubbed scanner."""

    class _Scanner:
        @staticmethod
        async def discover(timeout=5.0, return_adv=True):
            return found

    monkeypatch.setattr("app.ble.BleakScanner", _Scanner)
    asyncio.run_coroutine_threadsafe(ble._scan(), ble._loop).result(timeout=5)


def test_scan_choices_are_ordered_by_signal_strength() -> None:
    devices = [
        {"name": "Other room", "rssi": "-78"},
        {"name": "No reading", "rssi": "-"},
        {"name": "Desk", "rssi": "-41"},
    ]

    assert [item["name"] for item in _strongest_signal_first(devices)] == [
        "Desk",
        "Other room",
        "No reading",
    ]


def test_a_named_non_controller_stays_out_of_the_main_picker(controller, monkeypatch) -> None:
    _run_scan(
        controller,
        monkeypatch,
        {
            "possible": (
                _Device("SP630E", "AA:BB"),
                _Advertisement(rssi=-75),
            ),
            "appliance": (
                _Device("L/A_MitsubishiAdp", "CC:DD"),
                _Advertisement(rssi=-35),
            ),
        },
    )

    assert [item["name"] for item in controller._unknown_devices] == ["SP630E"]
    assert {record.name for record in controller.scan_snapshot().records} == {
        "SP630E",
        "L/A_MitsubishiAdp",
    }


def test_an_unnamed_controller_with_a_known_signature_is_offered(
    controller, monkeypatch
) -> None:
    _run_scan(
        controller,
        monkeypatch,
        {
            "known": (
                _Device(None, "AA:BB"),
                _Advertisement(manufacturer_data={0x5053: b"\x1f\x10"}),
            ),
        },
    )

    assert len(controller._unknown_devices) == 1
    assert controller._unknown_devices[0]["known_name"] == "BanlanX SP630E"


def test_picker_receives_supported_controllers_nearest_first(controller, monkeypatch) -> None:
    offered: list[list[dict]] = []
    controller.devices_discovered.connect(offered.append)

    _run_scan(
        controller,
        monkeypatch,
        {
            "far_strip": (
                _Device("ELK-BLEDOM", "AA:01"),
                _Advertisement(rssi=-76),
            ),
            "unknown": (
                _Device("SP630E", "AA:02"),
                _Advertisement(rssi=-35),
            ),
            "near_strip": (
                _Device("ELK-BLEDOM", "AA:03"),
                _Advertisement(rssi=-42),
            ),
        },
    )
    QApplication.instance().processEvents()

    assert offered, "the completed scan never reached the device picker"
    assert [item["address"] for item in offered[-1]] == ["AA:03", "AA:01", "AA:02"]
    assert [item["supported"] for item in offered[-1]] == [True, True, False]


def test_a_failed_capture_cannot_reuse_the_previous_devices_identity(
    controller, monkeypatch
) -> None:
    class _BrokenAdvertisement:
        local_name = "Neighbour appliance"
        rssi = -40
        service_uuids = []
        service_data = {}
        tx_power = None

        @property
        def manufacturer_data(self):
            raise RuntimeError("malformed advertisement")

    _run_scan(
        controller,
        monkeypatch,
        {
            "controller": (
                _Device("SP630E", "AA:01"),
                _Advertisement(rssi=-60),
            ),
            "appliance": (
                _Device("Neighbour appliance", "AA:02"),
                _BrokenAdvertisement(),
            ),
        },
    )

    assert [item["name"] for item in controller._unknown_devices] == [
        "SP630E"
    ]


def test_a_scan_records_every_device_including_the_ones_it_filters_out(controller, monkeypatch) -> None:
    """The controller nobody recognises is exactly the one a snapshot exists
    for, and it is the first thing dropped from the visible lists."""
    _run_scan(
        controller,
        monkeypatch,
        {
            "a": (
                _Device("ELK-BLEDOM", "AA:BB:CC:DD:EE:01"),
                _Advertisement(service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"]),
            ),
            "b": (
                _Device("SP630E", "AA:BB:CC:DD:EE:02"),
                _Advertisement(manufacturer_data={0x5A54: b"\x01\x02"}),
            ),
            "c": (_Device("Someone's Earbuds", "AA:BB:CC:DD:EE:03"), _Advertisement()),
            "d": (_Device(None, "AA:BB:CC:DD:EE:04"), _Advertisement()),
        },
    )

    snapshot = controller.scan_snapshot()
    names = sorted(record.name for record in snapshot.records)

    assert names == ["", "ELK-BLEDOM", "SP630E", "Someone's Earbuds"]

    offered = {device["name"] for device in controller._unknown_devices}
    assert "SP630E" in offered
    assert "Someone's Earbuds" not in offered
    # The anonymous one is not, and it is still in the snapshot above.
    assert "Unknown BLE Device" not in offered


def test_the_snapshot_carries_when_and_by_what_it_was_taken(controller, monkeypatch) -> None:
    _run_scan(controller, monkeypatch, {"a": (_Device("SP630E", "AA:BB"), _Advertisement())})

    snapshot = controller.scan_snapshot()

    assert snapshot.captured_at, "a capture with no time cannot be placed against an issue"
    assert snapshot.app_version == APP_VERSION
    assert snapshot.version == SNAPSHOT_VERSION


def test_an_empty_scan_leaves_an_empty_snapshot(controller, monkeypatch) -> None:
    _run_scan(controller, monkeypatch, {})

    assert controller.scan_snapshot().records == ()


def test_a_second_scan_replaces_the_first(controller, monkeypatch) -> None:
    """A snapshot describes one scan. A device that has since left would send a
    driver author chasing hardware that is not there."""
    _run_scan(controller, monkeypatch, {"a": (_Device("Old", "AA:BB"), _Advertisement())})
    _run_scan(controller, monkeypatch, {"b": (_Device("New", "CC:DD"), _Advertisement())})

    assert [record.name for record in controller.scan_snapshot().records] == ["New"]


def test_a_device_that_breaks_the_capture_does_not_break_the_scan(controller, monkeypatch) -> None:
    """Recording is bookkeeping; it never gets to cost the user their scan."""

    class _Hostile:
        @property
        def manufacturer_data(self):
            raise RuntimeError("this scanner is having a bad day")

        local_name = "Broken"
        rssi = -50
        service_uuids = ["0000fff0-0000-1000-8000-00805f9b34fb"]

    _run_scan(
        controller,
        monkeypatch,
        {
            "bad": (_Device("Broken", "AA:BB"), _Hostile()),
            "good": (
                _Device("ELK-BLEDOM", "CC:DD"),
                _Advertisement(service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"]),
            ),
        },
    )

    # The scan itself completed and still found the supported strip.
    assert [record.name for record in controller.scan_snapshot().records] == ["ELK-BLEDOM"]


def test_saving_a_snapshot_writes_a_file_that_reads_back(tmp_path) -> None:
    snapshot = ScanSnapshot(
        records=(),
        captured_at="2026-08-01T12:00:00",
        app_version="0.3.7",
    )
    path = tmp_path / "scan-snapshot.json"

    assert save_snapshot(path, snapshot, note="issue #2") is True

    reloaded = snapshot_from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert reloaded.note == "issue #2"
    assert reloaded.app_version == "0.3.7"


def test_a_write_that_fails_says_so_instead_of_raising(tmp_path) -> None:
    """Invoked from a button; a read-only folder should show a message, not take
    the app down."""
    target = tmp_path / "nowhere" / "scan.json"
    target.parent.write_text("I am a file, not a directory", encoding="utf-8")

    assert save_snapshot(target, ScanSnapshot()) is False

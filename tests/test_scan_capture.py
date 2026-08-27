"""Capturing a scan: what ends up in the snapshot, and what a capture may cost.

Scanning is the one thing that must keep working. Everything here is really
about that: recording is bookkeeping, and bookkeeping never gets to break the
feature it is recording.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import CancelledError as FuturesCancelledError

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.app_info import APP_VERSION
from app.ble import BleController
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


class _StubScanner:
    """Stands in for the library's scanner, and records its own lifecycle.

    The real one is entered, listened to, and left; the leaving is what stops
    it and releases the adapter. So this records both ends rather than only the
    advertisements — a scanner that was never left is the fault worth catching,
    and it looks identical from the results alone.
    """

    log: list[str] = []
    feed: list[tuple] = []
    fail_on_enter: BaseException | None = None

    def __init__(self, detection_callback=None, **_kwargs) -> None:
        self._callback = detection_callback

    async def __aenter__(self):
        # Raised before the scanner is marked active, which is what a failure
        # inside start() looks like: nothing is listening, nothing holds the
        # adapter, and there is nothing for a stop to undo. A stub that marked
        # itself active first would be describing a different failure and
        # demanding cleanup the real one does not need.
        if type(self).fail_on_enter is not None:
            raise type(self).fail_on_enter
        type(self).log.append("started")
        for device, advertisement in type(self).feed:
            self._callback(device, advertisement)
        return self

    async def __aexit__(self, *_exc):
        type(self).log.append("stopped")
        return False


def _install_scanner(monkeypatch, feed) -> type[_StubScanner]:
    """Point the adapter at the stub and make the listening instant."""
    _StubScanner.log = []
    _StubScanner.feed = list(feed)
    _StubScanner.fail_on_enter = None
    monkeypatch.setattr("app.ble.BleakScanner", _StubScanner)
    monkeypatch.setattr("app.ble.SCAN_SECONDS", 0.0)
    return _StubScanner


def _run_scan(ble, monkeypatch, found: dict) -> None:
    """Drive the real _scan() with a stubbed scanner."""
    _install_scanner(monkeypatch, list(found.values()))
    asyncio.run_coroutine_threadsafe(ble._scan(), ble._loop).result(timeout=5)


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


# ── the scanner is stopped, on every way out ──────────────────────────
def _events_of(ble) -> list[str]:
    """The scanner's lifecycle and the announcement, in the order they happened."""
    order: list[str] = []
    _StubScanner.log = order
    # Direct, so the moment of the announcement is recorded where it happens.
    # The ordinary queued delivery would run the slot later, on the interface
    # thread, and record an order that is about event loops rather than about
    # whether the scanner had stopped.
    ble.devices_discovered.connect(
        lambda _devices: order.append("announced"), Qt.DirectConnection
    )
    return order


def test_the_result_is_announced_only_after_the_scanner_has_stopped(controller, monkeypatch) -> None:
    """Announcing from inside the scan would put a list on screen that the rest
    of the five seconds then rearranges — and rearranges on exactly the single
    noisy reading this change exists to stop trusting."""
    _install_scanner(monkeypatch, [(_Device("ELK-BLEDOM", "AA:BB:CC:DD:EE:01"), _Advertisement(rssi=-55))])
    order = _events_of(controller)

    asyncio.run_coroutine_threadsafe(controller._scan(), controller._loop).result(timeout=5)

    assert order == ["started", "stopped", "announced"]


def test_a_scanner_that_fails_while_starting_leaves_nothing_running(controller, monkeypatch) -> None:
    """Nothing began, so there is nothing holding the adapter.

    The block is never entered when starting raises, so no stop follows — and
    none is owed. The failure that *would* owe one is the next test: a scanner
    that did start and then met trouble.
    """
    _install_scanner(monkeypatch, [])
    _StubScanner.fail_on_enter = RuntimeError("no radio today")
    order = _events_of(controller)

    with pytest.raises(RuntimeError):
        asyncio.run_coroutine_threadsafe(
            controller._listen_for_advertisements(), controller._loop
        ).result(timeout=5)

    assert order == [], "a scan that never started still claimed to be listening"


def test_a_scanner_is_left_when_the_listening_raises(controller, monkeypatch) -> None:
    """The failure that matters more: the scanner did start, and something went
    wrong afterwards."""
    _install_scanner(monkeypatch, [])
    order = _events_of(controller)

    async def _explode(_seconds):
        raise RuntimeError("interrupted")

    monkeypatch.setattr("app.ble.asyncio.sleep", _explode)

    with pytest.raises(RuntimeError):
        asyncio.run_coroutine_threadsafe(
            controller._listen_for_advertisements(), controller._loop
        ).result(timeout=5)

    assert order == ["started", "stopped"]


def test_a_cancelled_scan_still_leaves_the_scanner(controller, monkeypatch) -> None:
    """Cancellation is not an error and does not unwind by itself — it unwinds
    through the same block, which is the point of putting the stop there."""
    _install_scanner(monkeypatch, [])
    order = _events_of(controller)

    async def _cancelled(_seconds):
        raise asyncio.CancelledError()

    monkeypatch.setattr("app.ble.asyncio.sleep", _cancelled)

    # Surfaces here as the concurrent-futures cancellation, not the asyncio one.
    with pytest.raises(FuturesCancelledError):
        asyncio.run_coroutine_threadsafe(
            controller._listen_for_advertisements(), controller._loop
        ).result(timeout=5)

    assert order == ["started", "stopped"]


def test_scanning_for_another_strip_while_one_is_connected(controller, monkeypatch) -> None:
    """Adding an extra strip scans with the primary still open, and that path
    is the one where a scanner left running costs the connection as well as the
    scan. This proves the lifecycle only — whether the radio tolerates both at
    once is a question for real hardware.
    """
    _install_scanner(monkeypatch, [(_Device("ELK-BLEDOM", "AA:BB:CC:DD:EE:02"), _Advertisement(rssi=-61))])
    order = _events_of(controller)

    class _OpenClient:
        is_connected = True

        async def disconnect(self) -> None:
            """The adapter closes it on shutdown; a stand-in has to allow that."""
            type(self).is_connected = False

    controller._client = _OpenClient()

    asyncio.run_coroutine_threadsafe(controller._scan(), controller._loop).result(timeout=5)

    assert order == ["started", "stopped", "announced"]
    assert controller._client is not None, "the scan closed the connection it was scanning beside"


def test_the_whole_scan_of_readings_reaches_the_picker(controller, monkeypatch) -> None:
    """Five seconds of listening, and every reading kept.

    This is the point of the change reaching the place that will use it. The
    same strip advertises several times with readings that differ by nine dB,
    and the result carries all of them rather than whichever arrived last —
    which is what the ordering used to be decided on.
    """
    offered: list[list[dict]] = []
    controller.devices_discovered.connect(offered.append)
    strip = _Device("ELK-BLEDOM", "AA:BB:CC:DD:EE:07")
    _install_scanner(
        monkeypatch,
        [
            (strip, _Advertisement(rssi=-70)),
            (strip, _Advertisement(rssi=-61)),
            (strip, _Advertisement(rssi=-66)),
        ],
    )

    asyncio.run_coroutine_threadsafe(controller._scan(), controller._loop).result(timeout=5)
    QApplication.instance().processEvents()

    assert offered, "the completed scan never reached the device picker"
    assert offered[-1][0]["rssi_samples"] == (-70, -61, -66)


def test_an_unrecognised_device_keeps_its_readings_too(controller, monkeypatch) -> None:
    """The unknown group is ranked as well, and the report about it is what a
    driver gets written from."""
    offered: list[list[dict]] = []
    controller.devices_discovered.connect(offered.append)
    device = _Device("SP630E", "AA:BB:CC:DD:EE:08")
    _install_scanner(
        monkeypatch,
        [(device, _Advertisement(rssi=-50)), (device, _Advertisement(rssi=-58))],
    )

    asyncio.run_coroutine_threadsafe(controller._scan(), controller._loop).result(timeout=5)
    QApplication.instance().processEvents()

    unknown = [item for item in offered[-1] if item["supported"] is False]
    assert unknown, "the unrecognised device was not offered at all"
    assert unknown[0]["rssi_samples"] == (-50, -58)

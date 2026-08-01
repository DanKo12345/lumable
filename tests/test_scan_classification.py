"""Which unrecognised devices are worth showing, replayed over a capture.

The fixture is synthetic but shaped like a real scan in a block of flats: two
strips, one named unknown, one unknown that advertises a service, and anonymous
noise. Real captures contain neighbours' hardware and stay out of the repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.ble_drivers import detect_scan_driver
from app.scan_snapshot import (
    AdvertisementRecord,
    is_possible_controller,
    replay,
    snapshot_from_dict,
    sort_for_display,
)

FIXTURE = Path(__file__).parent / "fixtures" / "scan_mixed_room.json"


def _snapshot():
    return snapshot_from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _shown(snapshot):
    return [record for record in snapshot.records if is_possible_controller(record)]


def test_anonymous_noise_stays_out_of_the_list() -> None:
    """A device with neither a name nor a service gives the user nothing to
    recognise it by, and a block of flats is full of them."""
    hidden = [record for record in _snapshot().records if not is_possible_controller(record)]

    assert [record.address for record in hidden] == ["…:00:05", "…:00:06", "…:00:07"]


def test_a_named_unknown_device_is_still_offered() -> None:
    """Hiding a controller is the expensive mistake; a named device the user can
    dismiss at a glance is the cheap one."""
    names = [record.name for record in _shown(_snapshot())]

    assert "SP630E" in names
    assert "ELK-BLEDOM CE" in names


def test_an_unnamed_device_that_advertises_a_service_is_offered() -> None:
    shown = [record.address for record in _shown(_snapshot())]

    assert "…:00:04" in shown


def test_hidden_devices_are_still_in_the_snapshot() -> None:
    """The snapshot is the whole point: the device nobody recognises is exactly
    the one that gets filtered out of the visible list."""
    snapshot = _snapshot()

    assert len(snapshot.records) == 7
    assert len(_shown(snapshot)) == 4


def test_a_known_strip_is_still_detected_as_before() -> None:
    outcome = replay(_snapshot(), detect_scan_driver)
    by_name = {record.name: driver_id for record, driver_id in outcome}

    assert by_name["ELK-BLEDOM"] == "bledom"
    assert by_name["SP630E"] == "", "SP630E must not be claimed by an existing driver"


def test_the_list_is_ordered_by_signal_and_nothing_else() -> None:
    """Signal strength orders the list; it is not evidence of compatibility."""
    ordered = sort_for_display(_shown(_snapshot()))

    assert [record.rssi for record in ordered] == sorted(
        (record.rssi for record in ordered), reverse=True
    )


def test_sorting_is_stable_for_equal_signal() -> None:
    """Two strips at the same distance must not swap places between scans."""
    records = [
        AdvertisementRecord(name="first", rssi=-50),
        AdvertisementRecord(name="second", rssi=-50),
        AdvertisementRecord(name="third", rssi=-50),
    ]

    assert [record.name for record in sort_for_display(records)] == ["first", "second", "third"]


def test_a_device_with_no_signal_reading_sorts_last() -> None:
    records = [
        AdvertisementRecord(name="silent", rssi=None),
        AdvertisementRecord(name="far", rssi=-90),
    ]

    assert [record.name for record in sort_for_display(records)] == ["far", "silent"]


def test_the_placeholder_name_is_not_treated_as_a_real_one() -> None:
    """Every nameless device used to arrive as "Unknown BLE Device", and the
    "ble" in that placeholder matched the name heuristic — which offered every
    anonymous device in radio range as a possible strip."""
    assert is_possible_controller(AdvertisementRecord(name="", rssi=-60)) is False
    assert is_possible_controller(AdvertisementRecord(name="   ", rssi=-60)) is False

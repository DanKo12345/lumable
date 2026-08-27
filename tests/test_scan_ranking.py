"""The order the picker offers strips in.

Two properties matter and they pull against each other. Grouping has to beat
signal, or a neighbour's louder strip climbs above the one on this desk. Signal
has to be the median of a whole scan, or a distant device that got one lucky
reading climbs there instead. Both failures look identical to somebody in a
hurry: the wrong row, at the top.
"""

from __future__ import annotations

from app.scan_ranking import (
    GROUP_SUPPORTED,
    GROUP_TRUSTED,
    GROUP_UNKNOWN,
    by_signal,
    group_of,
    rank,
)


def _device(name: str, address: str, *, samples=(), supported: bool = True) -> dict:
    return {
        "name": name,
        "address": address,
        "supported": supported,
        "rssi_samples": tuple(samples),
    }


def _names(ranked) -> list[str]:
    return [item.device["name"] for item in ranked]


# ── which group ───────────────────────────────────────────────────────
def test_a_chosen_strip_leads_even_when_it_is_the_quietest() -> None:
    """The whole point of the grouping. A neighbour with a better aerial is
    still a neighbour."""
    mine = _device("Mine", "AA:01", samples=(-88, -87, -89))
    theirs = _device("Theirs", "AA:02", samples=(-40, -41, -39))

    order = rank([theirs, mine], trusted=["AA:01"])

    assert _names(order) == ["Mine", "Theirs"]
    assert order[0].group == GROUP_TRUSTED
    assert order[1].group == GROUP_SUPPORTED


def test_trust_beats_recognition_too() -> None:
    """A strip used for months belongs at the top on the day its advertisement
    arrives too thin for a driver to be sure of it."""
    assert group_of(_device("Mine", "AA:01", supported=False), ["AA:01"]) == GROUP_TRUSTED
    assert group_of(_device("Other", "AA:02", supported=False), ["AA:01"]) == GROUP_UNKNOWN
    assert group_of(_device("Other", "AA:02"), ["AA:01"]) == GROUP_SUPPORTED


def test_trust_is_matched_whatever_the_spelling() -> None:
    assert group_of(_device("Mine", "aa:bb:cc:dd:ee:01"), ["AA:BB:CC:DD:EE:01"]) == GROUP_TRUSTED
    assert group_of(_device("Mine", "AA:BB:CC:DD:EE:01"), [" aa:bb:cc:dd:ee:01 "]) == GROUP_TRUSTED


def test_an_empty_entry_in_the_trusted_list_trusts_nobody() -> None:
    """A blank line in the file must not turn every result into a chosen strip
    — including the ones with no address at all."""
    assert group_of(_device("Anyone", ""), ["", None]) == GROUP_SUPPORTED
    assert group_of(_device("Anyone", "AA:01"), ["", None]) == GROUP_SUPPORTED


def test_the_three_groups_come_out_in_one_order() -> None:
    devices = [
        _device("Unknown", "AA:03", samples=(-30, -31, -29), supported=False),
        _device("Supported", "AA:02", samples=(-50, -51, -49)),
        _device("Chosen", "AA:01", samples=(-70, -71, -69)),
    ]

    order = rank(devices, trusted=["AA:01"])

    assert _names(order) == ["Chosen", "Supported", "Unknown"]
    assert [item.group for item in order] == [GROUP_TRUSTED, GROUP_SUPPORTED, GROUP_UNKNOWN]


# ── which one leads inside a group ────────────────────────────────────
def test_within_a_group_the_stronger_median_leads() -> None:
    devices = [
        _device("Far", "AA:01", samples=(-80, -81, -79)),
        _device("Near", "AA:02", samples=(-45, -46, -44)),
        _device("Middle", "AA:03", samples=(-62, -63, -61)),
    ]

    assert _names(rank(devices)) == ["Near", "Middle", "Far"]


def test_one_lucky_reading_does_not_lift_a_distant_strip() -> None:
    """What the old ordering did, and the reason the whole scan is now kept.
    The far strip's single strong reading is better than anything the near one
    produced."""
    far = _device("Far", "AA:01", samples=(-85, -84, -86, -33))
    near = _device("Near", "AA:02", samples=(-58, -57, -59))

    assert _names(rank([far, near])) == ["Near", "Far"]


def test_a_device_heard_from_too_rarely_is_ordered_but_not_buried() -> None:
    """Thin evidence is not a weak signal. It is still ranked on what was
    heard, and only the confident *word* is withheld."""
    quiet_and_close = _device("Quiet", "AA:01", samples=(-40, -41))
    steady_and_far = _device("Steady", "AA:02", samples=(-75, -76, -74))

    order = rank([steady_and_far, quiet_and_close])

    assert _names(order) == ["Quiet", "Steady"]
    assert order[0].quality.is_confident is False
    assert order[1].quality.is_confident is True


def test_a_device_heard_from_at_all_leads_one_never_heard() -> None:
    """No believable reading is not a reading of zero, which no radio reports
    and which would put a silent device at the very top."""
    silent = _device("Silent", "AA:01", samples=())
    weak = _device("Weak", "AA:02", samples=(-95, -96, -94))

    assert _names(rank([silent, weak])) == ["Weak", "Silent"]


# ── the same list twice gives the same list ───────────────────────────
def test_two_identical_strips_come_out_in_a_settled_order() -> None:
    """Two of the same model in one room advertise under the same name at the
    same strength, and the picker must not shuffle them between scans."""
    first = _device("ELK-BLEDOM", "AA:BB:CC:DD:EE:02", samples=(-60, -60, -60))
    second = _device("ELK-BLEDOM", "AA:BB:CC:DD:EE:01", samples=(-60, -60, -60))

    forwards = [item.address for item in rank([first, second])]
    backwards = [item.address for item in rank([second, first])]

    assert forwards == backwards == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]


def test_the_input_order_does_not_leak_into_the_result() -> None:
    devices = [
        _device("Far", "AA:01", samples=(-80, -81, -79)),
        _device("Near", "AA:02", samples=(-45, -46, -44)),
        _device("Chosen", "AA:03", samples=(-70, -71, -69)),
    ]

    assert _names(rank(devices, trusted=["AA:03"])) == _names(
        rank(list(reversed(devices)), trusted=["AA:03"])
    )


def test_ranking_one_scan_cannot_depend_on_the_last_one() -> None:
    """Nothing is carried between calls. The test that would fail the day
    somebody adds a cache."""
    devices = [
        _device("Near", "AA:02", samples=(-45, -46, -44)),
        _device("Far", "AA:01", samples=(-80, -81, -79)),
    ]
    first = _names(rank(devices))

    rank([_device("Elsewhere", "BB:01", samples=(-10, -11, -9))], trusted=["BB:01"])

    assert _names(rank(devices)) == first


# ── the plain ordering, for callers with one kind of thing ────────────
def test_by_signal_returns_the_devices_themselves() -> None:
    """Used where there is a list to trim rather than a picker to fill, so it
    hands back what it was given rather than a wrapper."""
    far = _device("Far", "AA:01", samples=(-80, -81, -79))
    near = _device("Near", "AA:02", samples=(-45, -46, -44))

    assert by_signal([far, near]) == [near, far]


def test_anything_that_is_not_a_result_is_left_out() -> None:
    """A malformed entry must not stop a scan from being offered at all."""
    near = _device("Near", "AA:02", samples=(-45, -46, -44))

    assert by_signal([None, "strip", 42, near]) == [near]
    assert by_signal(None) == []


# ── the picker really is filled in that order ─────────────────────────
def test_the_picker_offers_a_chosen_strip_first() -> None:
    """The ordering reaching the place it is for. The adapter cannot do this —
    it can tell a recognised controller from an unrecognised one, but it has no
    idea which of them is this person's.
    """
    import pytest

    pytest.importorskip("PySide6")
    from app.ble_event_handler import BleEventHandler
    from app.scan_choices import address_of
    from tests.test_ble_event_handler import FakeHost

    host = FakeHost(
        _settings={
            "last_device_address": "",
            "trusted_device_addresses": ["AA:BB:CC:DD:EE:01"],
        }
    )
    handler = BleEventHandler(host)

    handler.populate_devices(
        [
            _device("Loud stranger", "AA:BB:CC:DD:EE:02", samples=(-38, -39, -37)),
            _device("Mine, far away", "AA:BB:CC:DD:EE:01", samples=(-86, -87, -85)),
        ]
    )

    # Only the rows that stand for a strip; the picker also carries the names
    # of the groups, which are not devices and never were.
    offered = [
        address
        for index in range(host.device_combo.count())
        if (address := address_of(host.device_combo.itemData(index)))
    ]
    assert offered == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]
    assert [item["address"] for item in host._devices] == offered, (
        "the list behind the picker disagrees with the picker"
    )

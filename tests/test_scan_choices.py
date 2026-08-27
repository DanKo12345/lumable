"""A row of the discovery field is asked what it is, not where it sits.

The picker used to hold one row per discovered controller in the same order as
the list behind it, and the selected position was used as an index into that
list. The two are about to stop matching — group headings and a row that
collapses the unrecognised devices both take a position without being a
controller — and nothing would have complained: the wrong strip would simply
have been opened.

So the tests here deliberately break the alignment. Every one of them arranges
a picker whose positions do *not* correspond to the list, and asks who gets
connected.
"""

from __future__ import annotations

import pytest

from app.scan_choices import (
    KIND_DEVICE,
    KIND_HEADING,
    KIND_NOTICE,
    ScanChoice,
    address_of,
    device_choice,
    find_device,
    heading_choice,
    kind_of,
    normalize_address,
    notice_choice,
)

pytest.importorskip("PySide6")

from app import ble_event_handler
from app.ble_event_handler import BleEventHandler
from tests.test_ble_event_handler import FakeBle, FakeCombo, FakeHost


def _strip(name: str, address: str, **extra) -> dict:
    device = {"name": name, "address": address, "rssi": "-60"}
    device.update(extra)
    return device


# ── the values a row can carry ────────────────────────────────────────
def test_only_a_device_row_answers_with_an_address() -> None:
    """A heading may well want to carry an address one day. It must still never
    be connected to, so what decides is the kind and not the presence."""
    assert address_of(device_choice("AA:BB:CC:DD:EE:FF")) == "AA:BB:CC:DD:EE:FF"
    assert address_of(notice_choice()) == ""
    assert address_of(ScanChoice(kind="notice", address="AA:BB:CC:DD:EE:FF")) == ""
    assert address_of(None) == ""


def test_a_row_nobody_taught_this_module_about_is_not_a_controller() -> None:
    """The default has to be the safe one. A value this module does not
    recognise is, by definition, not one it knows how to open a connection to —
    and the picker now holds several rows that are not devices at all.
    """
    assert kind_of(None) == KIND_NOTICE
    assert kind_of("AA:BB:CC:DD:EE:FF") == KIND_NOTICE
    assert kind_of(42) == KIND_NOTICE
    assert kind_of(device_choice("AA:BB:CC:DD:EE:FF")) == KIND_DEVICE
    assert kind_of(heading_choice()) == KIND_HEADING


def test_a_bare_address_is_not_proof_of_a_controller() -> None:
    """The old representation put a plain string here. Left accepted, every
    row built the old way would keep working and the guarantee would only hold
    for the rows somebody remembered to convert."""
    assert address_of("AA:BB:CC:DD:EE:FF") == ""


def test_addresses_are_compared_in_one_spelling() -> None:
    """A primary saved in one case and advertised in another is the same strip,
    and a comparison that says otherwise fails only on somebody else's machine.
    """
    assert normalize_address(" aa:bb:cc:dd:ee:ff ") == "AA:BB:CC:DD:EE:FF"
    devices = [_strip("Desk", "AA:BB:CC:DD:EE:FF")]
    assert find_device(devices, "aa:bb:cc:dd:ee:ff") is devices[0]


def test_a_row_naming_a_strip_no_longer_listed_finds_nothing() -> None:
    """Not a failure — the honest answer. The alternative is connecting to
    whichever controller happens to occupy that position instead."""
    assert find_device([_strip("Desk", "AA:BB:CC:DD:EE:FF")], "11:22:33:44:55:66") is None
    assert find_device([], "AA:BB:CC:DD:EE:FF") is None
    assert find_device([_strip("Desk", "AA:BB:CC:DD:EE:FF")], "") is None


# ── the picker, deliberately out of step with the list ────────────────
def _host_with_misaligned_picker() -> FakeHost:
    """Two strips, and a picker whose positions do not match the list.

    A notice takes the first row and the two controllers appear in the reverse
    order. Position 1 therefore holds the *second* strip while the list holds
    the first there — which is precisely the arrangement that used to open the
    wrong connection.
    """
    first = _strip("Desk strip", "AA:BB:CC:DD:EE:01")
    second = _strip("TV strip", "AA:BB:CC:DD:EE:02")
    host = FakeHost(_ble=FakeBle(), _devices=[first, second])
    host.device_combo = FakeCombo()
    host.device_combo.addItem("Scanning…", notice_choice())
    host.device_combo.addItem("TV strip", device_choice(second["address"]))
    host.device_combo.addItem("Desk strip", device_choice(first["address"]))
    return host


def test_the_highlighted_row_decides_which_strip_is_opened() -> None:
    """Row 1 holds the TV strip; the list holds the desk strip at index 1."""
    host = _host_with_misaligned_picker()
    handler = BleEventHandler(host)
    host.device_combo.setCurrentIndex(1)

    handler.handle_connect()

    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:02"], (
        "the strip at the matching *position* was opened instead of the selected one"
    )


def test_the_same_picker_read_at_another_row_opens_the_other_strip() -> None:
    """The pair: without this one, a helper that always returned the second
    device would satisfy the test above."""
    host = _host_with_misaligned_picker()
    handler = BleEventHandler(host)
    host.device_combo.setCurrentIndex(2)

    handler.handle_connect()

    assert host._ble.connected_to == ["AA:BB:CC:DD:EE:01"]


def test_a_row_that_is_not_a_strip_connects_to_nothing() -> None:
    """The first row is a notice. Under the old rule it indexed the first
    controller in the list and would have opened it."""
    host = _host_with_misaligned_picker()
    handler = BleEventHandler(host)
    host.device_combo.setCurrentIndex(0)

    handler.handle_connect()

    assert host._ble.connected_to == [], "a placeholder row opened a connection"
    assert host._ui_feedback.errors == ["error.select_controller_first"]


def test_adding_an_extra_strip_uses_the_highlighted_row_too(monkeypatch) -> None:
    """The other place that read a position. A picker out of step here mirrors
    the wrong controller, which is a second strip nobody asked for."""
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda settings: None)
    host = _host_with_misaligned_picker()
    host._is_connected = True
    host._settings = {"last_device_address": "", "extra_device_addresses": []}
    handler = BleEventHandler(host)
    host.device_combo.setCurrentIndex(1)

    handler.add_selected_as_mirror()

    assert host._ble.mirrored == ["AA:BB:CC:DD:EE:02"]

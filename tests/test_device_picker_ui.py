"""The picker with groups in it, and the rows that are not strips.

Adding headings and a row that opens the unrecognised devices puts things in
the list that must never be connected to. Nothing about a heading raises if it
is treated as a device — it simply has no address, and the code that used to
read a position would have opened whatever sat at that number instead.

The other half is what the rows say. A signal is described in words, because
the two useful facts inside a figure like −67 are how good it is and whether we
heard enough to say so; the figure itself belongs in the report, where somebody
debugging wants it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app import ble_event_handler
from app.ble_event_handler import BleEventHandler
from app.localization import localization_manager
from app.scan_choices import (
    KIND_BACK,
    KIND_DEVICE,
    KIND_HEADING,
    KIND_SHOW_UNKNOWN,
    address_of,
    kind_of,
)
from tests.test_ble_event_handler import FakeHost

MINE = "AA:BB:CC:DD:EE:01"
NEARBY = "AA:BB:CC:DD:EE:02"
STRANGER = "AA:BB:CC:DD:EE:03"


@pytest.fixture(autouse=True)
def _no_disk(monkeypatch):
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda _settings: None)


def _strip(address: str, name: str, *, supported: bool = True, samples=(-60, -61, -59)) -> dict:
    return {
        "name": name,
        "address": address,
        "supported": supported,
        "rssi": str(samples[-1]) if samples else "-",
        "rssi_samples": tuple(samples),
    }


def _rig(**settings):
    settings.setdefault("trusted_device_addresses", [MINE])
    host = FakeHost(_settings=settings)
    handler = BleEventHandler(host)
    handler.populate_devices(
        [
            _strip(MINE, "Desk strip"),
            _strip(NEARBY, "Hall strip", samples=(-70, -71, -69)),
            _strip(STRANGER, "Unknown BLE Device", supported=False, samples=(-88, -89, -87)),
        ]
    )
    return host, handler


def _kinds(host) -> list[str]:
    return [kind_of(host.device_combo.itemData(i)) for i in range(host.device_combo.count())]


# ── rows that are not strips ──────────────────────────────────────────
def test_the_picker_carries_headings_and_a_way_into_the_rest() -> None:
    host, _ = _rig()

    assert _kinds(host) == [
        KIND_HEADING,
        KIND_DEVICE,
        KIND_HEADING,
        KIND_DEVICE,
        KIND_SHOW_UNKNOWN,
    ]


def test_a_heading_cannot_be_connected_to() -> None:
    """It has no address, and the old picker would have opened whichever strip
    sat at the heading's position instead."""
    host, handler = _rig()
    host.device_combo.setCurrentIndex(0)
    assert kind_of(host.device_combo.currentData()) == KIND_HEADING

    handler.handle_connect()

    assert host._ble.connected_to == []
    assert host._ui_feedback.errors == ["error.select_controller_first"]


def test_the_row_that_opens_the_others_cannot_be_connected_to() -> None:
    host, handler = _rig()
    host.device_combo.setCurrentIndex(host.device_combo.count() - 1)
    assert kind_of(host.device_combo.currentData()) == KIND_SHOW_UNKNOWN

    handler.handle_connect()

    assert host._ble.connected_to == []


def test_only_a_strip_row_answers_with_a_device() -> None:
    host, handler = _rig()

    answered = []
    for index in range(host.device_combo.count()):
        host.device_combo.setCurrentIndex(index)
        answered.append(handler._selected_scan_device() is not None)

    assert answered == [False, True, False, True, False]


# ── the devices no driver claims ──────────────────────────────────────
def test_opening_the_others_shows_them_with_a_way_back() -> None:
    host, handler = _rig()

    handler._show_unknown_devices(True)

    assert _kinds(host) == [KIND_BACK, KIND_DEVICE]
    assert address_of(host.device_combo.itemData(1)) == STRANGER


def test_an_unrecognised_device_is_checked_rather_than_opened() -> None:
    """The only route by which a driver for one of these ever gets written, and
    it has to survive being moved behind another row."""
    host, handler = _rig()
    handler._show_unknown_devices(True)
    host.device_combo.setCurrentIndex(1)

    handler.handle_connect()

    assert host._ble.connected_to == [], "a guessed protocol was written to unknown hardware"
    assert host._ble.inspected == [STRANGER]


def test_coming_back_restores_the_strip_that_was_chosen() -> None:
    """Looking at what else is in the room is not a change of mind about which
    strip to connect to."""
    host, handler = _rig()
    for index in range(host.device_combo.count()):
        if address_of(host.device_combo.itemData(index)) == NEARBY:
            host.device_combo.setCurrentIndex(index)
            break

    handler._show_unknown_devices(True)
    handler._show_unknown_devices(False)

    assert address_of(host.device_combo.currentData()) == NEARBY
    assert handler._selected_scan_device()["address"] == NEARBY


def test_the_others_row_is_absent_when_there_are_none() -> None:
    host = FakeHost(_settings={"trusted_device_addresses": [MINE]})
    handler = BleEventHandler(host)

    handler.populate_devices([_strip(MINE, "Desk strip")])

    assert KIND_SHOW_UNKNOWN not in _kinds(host)
    assert KIND_HEADING not in _kinds(host), "a heading for the only group on screen"


# ── what a row says about the signal ──────────────────────────────────
def test_the_label_describes_the_signal_in_words() -> None:
    _, handler = _rig()

    label = handler._device_label(_strip(MINE, "Desk strip", samples=(-45, -46, -44)))

    assert "device.signal.strong" in label
    assert "dBm" not in label and "RSSI" not in label


def test_a_device_heard_from_twice_says_so_rather_than_guessing() -> None:
    _, handler = _rig()

    label = handler._device_label(_strip(MINE, "Desk strip", samples=(-45, -46)))

    assert "device.signal.insufficient" in label


def test_the_four_levels_are_translated_everywhere() -> None:
    """A missing translation shows up as a key in the picker — no error, no
    warning, just "device.signal.weak" where a sentence should be."""
    keys = [f"device.signal.{level}" for level in ("strong", "medium", "weak", "insufficient")]
    original = localization_manager.language

    try:
        for language in ("en", "ru", "es", "zh"):
            localization_manager.set_language(language)
            for key in keys:
                text = localization_manager.t(key)
                assert text and text != key, f"{key} is untranslated in {language}"
                assert "dBm" not in text, f"{key} names a unit in {language}"
    finally:
        localization_manager.set_language(original)


def test_the_group_names_are_translated_everywhere() -> None:
    keys = ("device.group.trusted", "device.group.nearby", "device.group.back")
    original = localization_manager.language

    try:
        for language in ("en", "ru", "es", "zh"):
            localization_manager.set_language(language)
            for key in keys:
                text = localization_manager.t(key)
                assert text and text != key, f"{key} is untranslated in {language}"
            counted = localization_manager.t("device.group.unknown", count=7)
            assert "7" in counted, f"the count is missing in {language}"
    finally:
        localization_manager.set_language(original)


# ── a strip you know, on a day it is not recognised ───────────────────
def test_a_chosen_strip_stays_yours_when_no_driver_claims_it() -> None:
    """An advertisement can arrive too thin for a driver to be sure of.

    That is a fact about one scan, not about whose strip it is. Filing it away
    with the neighbours' headphones — behind a row that has to be opened —
    hides the very device somebody is looking for, on the day it is hardest to
    find.
    """
    host = FakeHost(_settings={"trusted_device_addresses": [MINE]})
    handler = BleEventHandler(host)

    handler.populate_devices(
        [
            _strip(MINE, "Desk strip", supported=False),
            _strip(STRANGER, "Unknown BLE Device", supported=False, samples=(-88, -89, -87)),
        ]
    )

    assert _kinds(host) == [KIND_DEVICE, KIND_SHOW_UNKNOWN]
    assert address_of(host.device_combo.itemData(0)) == MINE

    handler._show_unknown_devices(True)

    assert [address_of(host.device_combo.itemData(i)) for i in range(host.device_combo.count())] == [
        "",
        STRANGER,
    ], "a chosen strip was filed away with the devices nobody recognises"


def test_a_chosen_strip_no_driver_claims_is_checked_not_guessed_at() -> None:
    """Being yours does not make a protocol known. Writing a guessed one to
    hardware is the thing the unsupported branch exists to refuse, and trust
    must not talk it round."""
    host = FakeHost(_settings={"trusted_device_addresses": [MINE]})
    handler = BleEventHandler(host)
    handler.populate_devices([_strip(MINE, "Desk strip", supported=False)])
    host.device_combo.setCurrentIndex(0)

    handler.handle_connect()

    assert host._ble.connected_to == []
    assert host._ble.inspected == [MINE]


# ── where the selection lands when there is no obvious answer ─────────
def test_a_scan_that_does_not_find_the_remembered_strip_still_lands_on_one() -> None:
    """Row zero is a heading once both groups are present.

    Resting there answers Connect with "choose a controller", which is an
    instruction to do the thing the person just did — and it happens on the
    ordinary morning when the strip that was last used is switched off.
    """
    host = FakeHost(
        _settings={
            "trusted_device_addresses": [MINE],
            "last_device_address": "AA:BB:CC:DD:EE:99",  # not in this scan
        }
    )
    handler = BleEventHandler(host)

    handler.populate_devices(
        [_strip(MINE, "Desk strip"), _strip(NEARBY, "Hall strip"), _strip(STRANGER, "Watch", supported=False)]
    )

    assert _kinds(host)[0] == KIND_HEADING, "this test is only about the case with headings"
    assert kind_of(host.device_combo.currentData()) == KIND_DEVICE
    assert handler._selected_scan_device() is not None


def test_coming_back_to_a_strip_that_has_gone_lands_on_one_that_has_not() -> None:
    """A scan can replace the list while the other devices are open."""
    host, handler = _rig()
    handler._show_unknown_devices(True)
    handler._selected_before_unknown = "AA:BB:CC:DD:EE:99"

    handler._show_unknown_devices(False)

    assert kind_of(host.device_combo.currentData()) == KIND_DEVICE
    assert handler._selected_scan_device() is not None

"""Which strips the app may reach for on its own, and how one earns that.

The rule is that trust comes from an act, never from an arrival. Pressing
Connect on a highlighted row is an act. A connection turning up is not: the app
opens connections by itself, and the one it finds on a day when your strip is
switched off is somebody else's.

That distinction has to hold at three doors, not one. The scan result that
auto-connects, the launch that reaches for the remembered address, and the
handler that writes down whatever reports itself connected — closing any two of
them leaves the third as a way in.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app import ble_event_handler
from app.ble_event_handler import BleEventHandler
from app.scan_choices import device_choice
from tests.test_ble_event_handler import FakeHost

MINE = "AA:BB:CC:DD:EE:01"
STRANGER = "AA:BB:CC:DD:EE:02"


@pytest.fixture(autouse=True)
def _no_disk(monkeypatch):
    monkeypatch.setattr(ble_event_handler, "save_settings", lambda _settings: None)


def _host(**settings) -> FakeHost:
    settings.setdefault("trusted_device_addresses", [])
    return FakeHost(_settings=settings)


def _offer(host, handler, *devices) -> None:
    """Put scan results in the picker the way a scan does."""
    host._devices = list(devices)
    host.device_combo.clear()
    for device in devices:
        host.device_combo.addItem(device["name"], device_choice(device["address"]))
    host.device_combo.setCurrentIndex(0)


def _strip(address: str, name: str = "ELK-BLEDOM", **extra) -> dict:
    device = {"name": name, "address": address, "rssi": "-55", "supported": True}
    device.update(extra)
    return device


def _trusted(host) -> list[str]:
    return host._settings.get("trusted_device_addresses", [])


# ── 1 and 2: the scan that finds exactly one controller ───────────────
def test_a_single_unknown_controller_is_offered_and_not_opened() -> None:
    """One supported controller in range is not evidence that it is yours. It
    is evidence that yours is the only one switched on, or that it is not."""
    host = _host()
    handler = BleEventHandler(host)

    handler.populate_devices([_strip(STRANGER)])

    assert host._ble.connected_to == [], "a strip nobody chose was opened"
    assert host._connect_in_progress is False
    assert host.device_combo.count() == 1, "and it was not offered either"


def test_a_single_chosen_controller_is_still_opened_for_you() -> None:
    """The convenience is kept for the case it was written for: your strip, on
    its own, found again."""
    host = _host(trusted_device_addresses=[MINE])
    handler = BleEventHandler(host)

    handler.populate_devices([_strip(MINE)])

    assert host._ble.connected_to == [MINE]


def test_the_launch_reaches_only_for_a_chosen_strip() -> None:
    """The second door. Closing only the scan would leave every launch doing
    what the scan is no longer allowed to."""
    remembered = _host(last_device_address=STRANGER, last_device_name="Whoever")
    BleEventHandler(remembered).start_autoconnect()
    assert remembered._ble.connected_to == []

    chosen = _host(
        last_device_address=MINE,
        last_device_name="Desk strip",
        trusted_device_addresses=[MINE],
    )
    BleEventHandler(chosen).start_autoconnect()
    assert chosen._ble.connected_to == [MINE]


# ── 3, 4 and 5: what a connection is allowed to write down ────────────
def test_pressing_connect_and_succeeding_is_what_grants_trust() -> None:
    host = _host()
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(MINE))

    handler.handle_connect()
    handler.on_connected_changed(True, MINE)

    assert _trusted(host) == [MINE]
    assert host._settings["last_device_address"] == MINE


def test_pressing_connect_and_failing_grants_nothing() -> None:
    """The attempt ended. Nothing about it says this strip is theirs, and the
    address must not be left waiting for the next connection to adopt it."""
    host = _host()
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(MINE))

    handler.handle_connect()
    handler.show_error("it did not answer")
    handler.on_connected_changed(True, MINE)

    assert _trusted(host) == []
    assert host._settings.get("last_device_address", "") == ""


def test_a_connection_nobody_asked_for_is_not_written_down() -> None:
    """The third door, and the one that was standing wide open: any address
    reporting itself connected became the remembered strip."""
    host = _host()
    handler = BleEventHandler(host)

    handler.on_connected_changed(True, STRANGER)

    assert _trusted(host) == []
    assert host._settings.get("last_device_address", "") == "", (
        "an unchosen strip became the one this app reaches for at every launch"
    )
    assert host._is_connected is True, "the connection itself is still real and shown"


def test_a_late_success_cannot_be_read_as_the_answer_to_a_newer_attempt() -> None:
    """Two presses, and the first strip answers after the second was asked.

    Neither may be trusted on that evidence: the second has not answered at
    all, and the first is answering a question that was withdrawn.
    """
    host = _host()
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(MINE), _strip(STRANGER))

    host.device_combo.setCurrentIndex(0)
    handler.handle_connect()
    host._connect_in_progress = False
    host.device_combo.setCurrentIndex(1)
    handler.handle_connect()

    handler.on_connected_changed(True, MINE)

    assert _trusted(host) == [], "a withdrawn attempt granted trust"
    assert host._settings.get("last_device_address", "") == ""


def test_a_check_started_after_a_connect_ends_the_earlier_promise() -> None:
    """The second press need not be another connect.

    Pressing Connect on a strip and then, before it answers, pressing an
    unrecognised row starts a compatibility check — which sets no promise of
    its own. Without the attempt being ended where it begins, the first
    strip's promise would sit there waiting for whatever connected next.
    """
    host = _host()
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(MINE), _strip(STRANGER, "Unknown", supported=False))

    host.device_combo.setCurrentIndex(0)
    handler.handle_connect()
    host._connect_in_progress = False
    host.device_combo.setCurrentIndex(1)
    handler.handle_connect()  # a check, not a connect

    assert handler._pending_trusted_primary == ""
    handler.on_connected_changed(True, MINE)

    assert _trusted(host) == []
    assert host._settings.get("last_device_address", "") == ""


def test_a_check_in_progress_refuses_to_start_a_connection() -> None:
    """Why a promise cannot outlive a check in the first place.

    The two never overlap: a check refuses a connect while it runs, and a check
    makes no promise of its own. The clearing done when a check finishes is
    belt and braces for an ordering that does not exist today, and this is the
    invariant it is bracing.
    """
    host = _host()
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(MINE))
    host._inspect_in_progress = True

    handler.handle_connect()

    assert host._ble.connected_to == []
    assert handler._pending_trusted_primary == ""
    assert host._ui_feedback.errors == ["error.wait_inspect"]


# ── 7, 8 and 9: the extra strip ───────────────────────────────────────
def _connected_host(**settings) -> FakeHost:
    host = _host(**settings)
    host._is_connected = True
    return host


def test_adding_an_extra_strip_that_appears_grants_trust() -> None:
    host = _connected_host(last_device_address=MINE, trusted_device_addresses=[MINE])
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(STRANGER, "TV strip"))

    handler.add_selected_as_mirror()
    handler.refresh_mirror_list([STRANGER])

    assert STRANGER in _trusted(host)


def test_adding_an_extra_strip_that_never_appears_grants_nothing() -> None:
    """Pressed, and the strip did not join. Nothing was chosen in the end."""
    host = _connected_host(last_device_address=MINE, trusted_device_addresses=[MINE])
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(STRANGER, "TV strip"))

    handler.add_selected_as_mirror()
    handler.refresh_mirror_list([])

    assert STRANGER not in _trusted(host)


def test_a_saved_extra_coming_back_on_its_own_grants_nothing() -> None:
    """It was chosen on the day it was added, and the migration carried that
    over. A quiet restore is not a fresh decision about anything."""
    host = _connected_host(last_device_address=MINE, trusted_device_addresses=[MINE])
    handler = BleEventHandler(host)

    handler.refresh_mirror_list([STRANGER])

    assert _trusted(host) == [MINE], "a strip that simply reappeared was adopted"


# ── 10: reading a device is not choosing it ───────────────────────────
def test_checking_an_unrecognised_device_never_grants_trust() -> None:
    """A compatibility check reads a device's services and writes nothing. The
    person pressing it is asking what something is, not adopting it."""
    host = _host()
    handler = BleEventHandler(host)
    _offer(host, handler, _strip(STRANGER, "Unknown BLE Device", supported=False))

    handler.handle_connect()  # an unsupported row starts a check, not a connect

    assert host._inspect_in_progress is True
    assert host._ble.connected_to == []
    assert handler._pending_trusted_primary == ""

    handler.on_connected_changed(True, STRANGER)

    assert _trusted(host) == []
    assert host._settings.get("last_device_address", "") == ""

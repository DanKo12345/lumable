"""Extra strips must survive a restart — and a dropped link.

A multi-strip setup used to shrink to one strip after every launch: the extras
were session-only, so groups and group-targeted scenes silently resolved to
nothing. Only addresses are stored; the label comes from ``device_names`` and
the driver is re-detected on connect.
"""

from __future__ import annotations

import pytest

from app.device_names import validate_extra_addresses

pytest.importorskip("PySide6")

from app.ble_event_handler import BleEventHandler
from tests.test_ble_event_handler import FakeBle, FakeHost  # reuse the existing doubles


class ExtrasBle(FakeBle):
    def __init__(self, mirrors: list[str] | None = None) -> None:
        super().__init__()
        self.mirrors = list(mirrors or [])
        self.restored: list[str] = []
        self.removed: list[str] = []

    def mirror_addresses(self) -> list[str]:
        return list(self.mirrors)

    def restore_mirror_device(self, address: str) -> None:
        self.restored.append(address)

    def remove_mirror_device(self, address: str) -> None:
        self.removed.append(address)


def _handler(saved: list[str] | None = None, mirrors: list[str] | None = None):
    host = FakeHost(_ble=ExtrasBle(mirrors))
    if saved is not None:
        host._settings["extra_device_addresses"] = list(saved)
    return BleEventHandler(host), host


# ── validation ────────────────────────────────────────────────────────

def test_addresses_are_normalised_and_deduplicated() -> None:
    assert validate_extra_addresses(["aa:bb", "AA:BB", " cc:dd ", "", None]) == ["AA:BB", "CC:DD"]
    assert validate_extra_addresses("not a list") == []
    assert validate_extra_addresses(None) == []


# ── remembering ───────────────────────────────────────────────────────

def test_a_live_extra_is_remembered() -> None:
    handler, host = _handler(saved=[])
    handler.refresh_mirror_list(["AA:BB"])
    assert host._settings["extra_device_addresses"] == ["AA:BB"]


def test_losing_the_link_does_not_forget_the_set() -> None:
    """A dropout emits an empty mirror list — that must not erase the setup."""
    handler, host = _handler(saved=["AA:BB", "CC:DD"])
    handler.refresh_mirror_list([])
    assert host._settings["extra_device_addresses"] == ["AA:BB", "CC:DD"]


def test_remove_disconnects_and_forgets() -> None:
    handler, host = _handler(saved=["AA:BB", "CC:DD"], mirrors=["AA:BB", "CC:DD"])
    handler._remove_extra("AA:BB")
    assert host._settings["extra_device_addresses"] == ["CC:DD"]
    assert host._ble.removed == ["AA:BB"]


# ── restoring ─────────────────────────────────────────────────────────

def test_saved_extras_are_restored_after_the_primary_connects() -> None:
    handler, host = _handler(saved=["AA:BB", "CC:DD"], mirrors=[])
    handler._restore_saved_extras("EE:FF")
    assert host._ble.restored == ["AA:BB", "CC:DD"]


def test_restore_skips_the_primary_and_anything_already_live() -> None:
    handler, host = _handler(saved=["AA:BB", "CC:DD", "EE:FF"], mirrors=["CC:DD"])
    handler._restore_saved_extras("EE:FF")
    assert host._ble.restored == ["AA:BB"]  # CC:DD is up, EE:FF is the primary now


def test_reconnect_restores_again_without_stacking_retries() -> None:
    """A reconnect tears every extra down, so each primary connect restores —
    but it must restart the schedule, not stack a second timer per strip."""
    handler, host = _handler(saved=["AA:BB"], mirrors=[])
    handler._restore_saved_extras("EE:FF")
    first_timer = handler._restore_timers.get("AA:BB")
    handler._restore_saved_extras("EE:FF")

    assert host._ble.restored == ["AA:BB", "AA:BB"]  # attempted on both connects
    assert list(handler._restore_timers) == ["AA:BB"]  # exactly one pending retry
    assert handler._restore_timers["AA:BB"] is not first_timer
    assert first_timer.isActive() is False  # the superseded one was stopped


# ── bounded retry ─────────────────────────────────────────────────────

def test_retry_reattempts_while_the_strip_is_missing() -> None:
    handler, host = _handler(saved=["AA:BB"], mirrors=[])
    host._is_connected = True
    handler._retry_restore("AA:BB", 1)
    assert host._ble.restored == ["AA:BB"]
    assert "AA:BB" in handler._restore_timers  # next attempt queued


def test_retry_stops_once_the_strip_is_up() -> None:
    handler, host = _handler(saved=["AA:BB"], mirrors=["AA:BB"])
    host._is_connected = True
    handler._retry_restore("AA:BB", 1)
    assert host._ble.restored == []
    assert handler._restore_timers == {}


def test_retry_stops_when_the_strip_was_removed() -> None:
    handler, host = _handler(saved=[], mirrors=[])
    host._is_connected = True
    handler._retry_restore("AA:BB", 1)
    assert host._ble.restored == []
    assert handler._restore_timers == {}


def test_retry_stops_without_a_primary() -> None:
    handler, host = _handler(saved=["AA:BB"], mirrors=[])
    host._is_connected = False
    handler._retry_restore("AA:BB", 1)
    assert host._ble.restored == []
    assert handler._restore_timers == {}


def test_retry_is_bounded() -> None:
    from app.ble_event_handler import RESTORE_BACKOFF_SECONDS

    handler, host = _handler(saved=["AA:BB"], mirrors=[])
    host._is_connected = True
    handler._schedule_restore("AA:BB", len(RESTORE_BACKOFF_SECONDS))
    assert handler._restore_timers == {}  # gave up instead of retrying forever


def test_removing_a_strip_cancels_its_retry() -> None:
    handler, host = _handler(saved=["AA:BB"], mirrors=[])
    host._is_connected = True
    handler._schedule_restore("AA:BB", 0)
    timer = handler._restore_timers["AA:BB"]

    handler._remove_extra("AA:BB")

    assert handler._restore_timers == {}
    assert timer.isActive() is False


def test_losing_the_primary_cancels_every_retry() -> None:
    handler, host = _handler(saved=["AA:BB", "CC:DD"], mirrors=[])
    host._is_connected = True
    handler._schedule_restore("AA:BB", 0)
    handler._schedule_restore("CC:DD", 0)

    handler.on_connected_changed(False, "")

    assert handler._restore_timers == {}


def test_a_strip_coming_up_cancels_its_retry() -> None:
    handler, host = _handler(saved=["AA:BB"], mirrors=[])
    host._is_connected = True
    handler._schedule_restore("AA:BB", 0)

    handler.refresh_mirror_list(["AA:BB"])  # it joined

    assert handler._restore_timers == {}


# ── promotion keeps the stored set truthful ───────────────────────────

def test_promoting_moves_the_new_primary_out_of_the_extras() -> None:
    handler, host = _handler(saved=["CC:DD"], mirrors=["AA:BB"])
    host._settings["last_device_address"] = "AA:BB"
    handler.on_primary_changed("CC:DD", "TV")
    stored = host._settings["extra_device_addresses"]
    assert "CC:DD" not in stored          # it is the main strip now
    assert "AA:BB" in stored              # the old primary was kept as an extra


def test_promoting_keeps_offline_extras_remembered() -> None:
    handler, host = _handler(saved=["CC:DD", "99:99"], mirrors=["AA:BB"])
    host._settings["last_device_address"] = "AA:BB"
    handler.on_primary_changed("CC:DD", "TV")
    assert "99:99" in host._settings["extra_device_addresses"]

"""Whether a tracked command really wrote anything.

Mocked at the lowest sensible level — the GATT write attempt — because this is
the last place a false success can be caught. The executor above trusts
``BleOperationResult`` and has no way to see past it.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from app.ble import RESULT_SUCCESS, RESULT_UNAVAILABLE, BleController


class _Characteristic:
    uuid = "0000fff3-0000-1000-8000-00805f9b34fb"
    properties = ("write-without-response",)


class _Driver:
    def power_payloads(self, enabled):
        return [b"\x7e\x04"]

    def color_payloads(self, red, green, blue):
        return [b"\x7e\x05"]

    def brightness_payloads(self, value):
        return [b"\x7e\x06"]


class _Pacer:
    def reserve(self):
        return 0


class _Mirror:
    def __init__(self) -> None:
        self.address = "MIRROR"
        self.driver = _Driver()
        self.pacer = _Pacer()
        self.client = object()
        self.write_characteristics = [_Characteristic()]
        self.write_characteristic = self.write_characteristics[0]


@pytest.fixture()
def controller():
    ble = BleController()
    try:
        yield ble
    finally:
        ble.shutdown()


def _results(ble) -> list:
    collected: list = []
    ble.operation_finished.connect(collected.append)
    return collected


def _wait(results: list, count: int = 1, timeout: float = 3.0) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    deadline = time.time() + timeout
    while len(results) < count and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _arrange(ble, *, primary: bool, mirrors: int, mirror_writes: bool) -> None:
    """Stand in for a connected strip without touching real Bluetooth."""
    mirror_list = [_Mirror() for _ in range(mirrors)]
    ble._plan_addresses = lambda addresses: {
        "primary": primary,
        "mirrors": [m.address for m in mirror_list],
        "sync_primary": True,
    }
    ble._primary_writable = lambda plan: primary
    ble._targeted_mirrors = lambda plan: mirror_list
    ble._require_driver = lambda: _Driver()
    ble._connection_candidates = lambda conn: conn.write_characteristics

    async def write_many(payloads, label, quiet=False):
        return None

    async def write_attempt(characteristic, payload, prefer_response, client=None):
        return None if mirror_writes else "refused"

    ble._write_many = write_many
    ble._write_attempt = write_attempt


def test_a_primary_write_succeeds_and_updates_the_cache(controller) -> None:
    results = _results(controller)
    _arrange(controller, primary=True, mirrors=0, mirror_writes=True)
    controller._desired_power_on = False

    controller.set_power_for_address_tracked(True, "AA:BB")
    _wait(results)

    assert results[0].ok is True
    assert results[0].code == RESULT_SUCCESS
    assert controller._desired_power_on is True


def test_a_mirror_only_write_succeeds(controller) -> None:
    results = _results(controller)
    _arrange(controller, primary=False, mirrors=1, mirror_writes=True)

    controller.set_color_for_address_tracked(10, 20, 30, "AA:BB")
    _wait(results)

    assert results[0].ok is True


def test_a_mirror_that_refuses_every_write_is_unavailable(controller) -> None:
    """The false success this guards against: the mirror call returned without
    raising, but nothing reached the strip."""
    results = _results(controller)
    _arrange(controller, primary=False, mirrors=1, mirror_writes=False)

    controller.set_color_for_address_tracked(10, 20, 30, "AA:BB")
    _wait(results)

    assert results[0].ok is False
    assert results[0].code == RESULT_UNAVAILABLE


def test_a_failed_mirror_write_leaves_the_primary_cache_alone(controller) -> None:
    results = _results(controller)
    _arrange(controller, primary=False, mirrors=1, mirror_writes=False)
    before = (controller._last_red, controller._last_green, controller._last_blue)

    controller.set_color_for_address_tracked(1, 2, 3, "AA:BB")
    _wait(results)

    assert (controller._last_red, controller._last_green, controller._last_blue) == before


def test_a_working_primary_carries_a_failing_mirror(controller) -> None:
    """One target reached is enough for the command to have happened; the
    mirror's own trouble is not the rule's failure."""
    results = _results(controller)
    _arrange(controller, primary=True, mirrors=1, mirror_writes=False)

    controller.set_brightness_for_address_tracked(42, "AA:BB")
    _wait(results)

    assert results[0].ok is True
    assert controller._last_brightness == 42


def test_a_tracked_command_refuses_a_vague_target(controller) -> None:
    """A tracked call covering several strips would report success as soon as
    any of them accepted, hiding a scene that only half applied."""
    for bad in (None, "", "   ", ["AA:BB", "CC:DD"]):
        with pytest.raises(ValueError):
            controller.set_power_for_address_tracked(True, bad)

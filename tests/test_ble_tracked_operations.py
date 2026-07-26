"""Tracked BLE operations: exactly one result per id, in every branch.

Automation cannot confirm a rule as applied without this, so the guarantees are
pinned here rather than left to the reader of ble.py. No hardware is involved —
the commands are plain coroutines put through the controller's real loop.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

pytest.importorskip("PySide6")

from app.ble import (
    NO_TARGET,
    RESULT_BLE_ERROR,
    RESULT_CANCELLED,
    RESULT_SHUTDOWN,
    RESULT_SUCCESS,
    RESULT_UNAVAILABLE,
    BleController,
)


@pytest.fixture()
def controller():
    ble = BleController()
    try:
        yield ble
    finally:
        ble.shutdown()


def _collect(ble) -> list:
    results: list = []
    ble.operation_finished.connect(results.append)
    return results


def _wait_for(results: list, count: int = 1, timeout: float = 3.0) -> None:
    """Spin the Qt loop while waiting.

    ``operation_finished`` is emitted from the BLE thread, so Qt delivers it as
    a queued connection — nothing arrives unless an event loop is turning. The
    real app always has one; a test has to do it by hand.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    deadline = time.time() + timeout
    while len(results) < count and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_a_successful_command_reports_once(controller) -> None:
    results = _collect(controller)

    async def work():
        await asyncio.sleep(0)

    operation_id = controller._submit(work(), tracked=True)
    _wait_for(results)

    assert [(r.operation_id, r.ok, r.code) for r in results] == [
        (operation_id, True, RESULT_SUCCESS)
    ]


def test_a_result_that_lands_before_submit_returns_is_not_lost(controller) -> None:
    """The future can finish before add_done_callback returns, running the
    callback inline — before the caller has an id to register it against."""
    results = _collect(controller)
    started = asyncio.Event()

    async def instant():
        return None

    # Warm the loop so the coroutine below completes as early as possible.
    controller._submit(instant(), tracked=False)
    time.sleep(0.05)
    del started

    operation_id = controller._submit(instant(), tracked=True)
    _wait_for(results)

    assert len(results) == 1
    assert results[0].operation_id == operation_id


def test_a_failing_command_reports_the_error_once(controller) -> None:
    results = _collect(controller)

    async def boom():
        raise RuntimeError("no strip")

    operation_id = controller._submit(boom(), tracked=True)
    _wait_for(results)

    assert len(results) == 1
    assert results[0].operation_id == operation_id
    assert results[0].ok is False
    assert results[0].code == RESULT_BLE_ERROR
    assert "no strip" in results[0].message


def test_a_command_with_no_target_is_unavailable_not_a_success(controller) -> None:
    """It wrote nothing, so it must not confirm a rule as applied."""
    results = _collect(controller)

    async def nowhere():
        return NO_TARGET

    controller._submit(nowhere(), tracked=True)
    _wait_for(results)

    assert results[0].ok is False
    assert results[0].code == RESULT_UNAVAILABLE


def test_cancelling_an_operation_waiting_for_the_lock(controller) -> None:
    """The queued command never runs, and says so exactly once."""
    results = _collect(controller)
    release = asyncio.Event()

    async def blocker():
        await asyncio.wait_for(_wait_event(release, controller), timeout=2.0)

    async def queued():
        raise AssertionError("a cancelled command must not run")

    first = controller._submit(blocker(), tracked=True)
    time.sleep(0.05)
    second = controller._submit(queued(), tracked=True)

    assert controller.cancel_operation(second) is True
    _wait_for(results)

    cancelled = [r for r in results if r.operation_id == second]
    assert len(cancelled) == 1
    assert cancelled[0].code == RESULT_CANCELLED

    controller._loop.call_soon_threadsafe(release.set)
    _wait_for(results, count=2)
    assert {r.operation_id for r in results} == {first, second}


def test_cancelling_a_finished_operation_reports_false(controller) -> None:
    results = _collect(controller)

    async def work():
        return None

    operation_id = controller._submit(work(), tracked=True)
    _wait_for(results)

    assert controller.cancel_operation(operation_id) is False
    assert len(results) == 1, "cancelling twice must not produce a second result"


def test_a_command_submitted_after_shutdown_reports_shutdown() -> None:
    ble = BleController()
    ble.shutdown()
    results = _collect(ble)

    async def work():
        return None

    operation_id = ble._submit(work(), tracked=True)
    _wait_for(results)

    assert [(r.operation_id, r.ok, r.code) for r in results] == [
        (operation_id, False, RESULT_SHUTDOWN)
    ]


def test_untracked_commands_stay_silent(controller) -> None:
    """The historical path must not start emitting at every existing call site."""
    results = _collect(controller)

    async def work():
        return None

    assert controller._submit(work(), tracked=False) is None
    _wait_for(results, count=1, timeout=0.3)
    assert results == []


async def _wait_event(event: asyncio.Event, controller) -> None:
    await event.wait()


def test_the_slot_never_runs_before_the_caller_has_the_id(controller) -> None:
    """Delivery is queued precisely so a slot cannot fire inside _submit, when
    the variable it is supposed to match has not been assigned yet."""
    seen: list = []
    holder: dict = {}

    def on_result(result):
        # If this runs inline, the assignment below has not happened.
        seen.append(holder.get("id"))

    controller.operation_finished.connect(on_result)

    async def instant():
        return None

    holder["id"] = controller._submit(instant(), tracked=True)
    _wait_for(seen)

    assert seen == [holder["id"]]


def test_a_rejected_submit_also_reports_after_returning() -> None:
    """The early-refusal branch is the easiest one to deliver too soon."""
    ble = BleController()
    ble.shutdown()
    seen: list = []
    holder: dict = {}
    ble.operation_finished.connect(lambda result: seen.append(holder.get("id")))

    async def work():
        return None

    holder["id"] = ble._submit(work(), tracked=True)
    _wait_for(seen)

    assert seen == [holder["id"]]


def test_concurrent_cancels_racing_the_result_produce_one_signal(controller) -> None:
    """Exactly-once must hold when the threads genuinely collide, not merely
    when the calls happen to be sequential: the done callback runs on the BLE
    thread while cancels come from wherever the UI happens to be."""
    results = _collect(controller)
    barrier = threading.Barrier(6)

    async def work():
        await asyncio.sleep(0.05)

    operation_id = controller._submit(work(), tracked=True)

    def cancel() -> None:
        barrier.wait(timeout=3)
        controller.cancel_operation(operation_id)

    threads = [threading.Thread(target=cancel) for _ in range(5)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=3)  # release them together, and with the running command
    for thread in threads:
        thread.join(timeout=3)
    _wait_for(results)

    assert len(results) == 1
    assert controller._operations == {}


def test_the_registry_is_empty_once_an_operation_is_done(controller) -> None:
    """Separate dictionaries for results and delivery grew for the life of the
    process; one state object lets the whole entry go."""
    results = _collect(controller)

    async def work():
        return None

    controller._submit(work(), tracked=True)
    _wait_for(results)

    assert controller._operations == {}


def test_the_registry_is_empty_after_a_cancel(controller) -> None:
    results = _collect(controller)
    release = asyncio.Event()

    async def blocker():
        await asyncio.wait_for(_wait_event(release, controller), timeout=2.0)

    async def queued():
        raise AssertionError("a cancelled command must not run")

    first = controller._submit(blocker(), tracked=True)
    time.sleep(0.05)
    second = controller._submit(queued(), tracked=True)
    controller.cancel_operation(second)
    controller._loop.call_soon_threadsafe(release.set)
    _wait_for(results, count=2)

    assert {r.operation_id for r in results} == {first, second}
    assert controller._operations == {}


def test_a_running_command_keeps_the_lock_until_it_actually_finishes(controller) -> None:
    """Cancelling a *running* command must not free the lock early: the next
    command would then overlap a write still on its way to the strip."""
    results = _collect(controller)
    order: list[str] = []
    release = asyncio.Event()

    async def running():
        order.append("running-start")
        await _wait_event(release, controller)
        order.append("running-end")

    async def follower():
        order.append("follower-start")

    first = controller._submit(running(), tracked=True)
    time.sleep(0.05)
    assert order == ["running-start"]

    assert controller.cancel_operation(first) is True
    assert controller.is_cancel_requested(first) is True
    second = controller._submit(follower(), tracked=True)
    time.sleep(0.05)
    assert order == ["running-start"], "the follower started while the first still held the lock"

    controller._loop.call_soon_threadsafe(release.set)
    _wait_for(results, count=2)

    assert order == ["running-start", "running-end", "follower-start"]
    cancelled = next(r for r in results if r.operation_id == first)
    assert cancelled.ok is False
    assert cancelled.code == RESULT_CANCELLED
    assert next(r for r in results if r.operation_id == second).ok is True


def test_a_tracked_command_with_nothing_to_write_to_is_unavailable(controller) -> None:
    """Not connected and no mirrors: the command reached no strip, so it must
    not confirm a rule as applied."""
    results = _collect(controller)

    operation_id = controller.set_power_for_address_tracked(True, "AA:BB")
    _wait_for(results)

    assert results[0].operation_id == operation_id
    assert results[0].ok is False
    assert results[0].code == RESULT_UNAVAILABLE


def test_a_failed_power_command_does_not_move_the_desired_state(controller) -> None:
    """The cache is what reconnect restores. Recording an intent that never
    reached the strip would have the next recovery act on a command that never
    happened."""
    results = _collect(controller)
    before = controller._desired_power_on

    controller.set_power_for_address_tracked(not before, "AA:BB")
    _wait_for(results)

    assert controller._desired_power_on is before


def test_every_tracked_command_reports_its_own_id(controller) -> None:
    results = _collect(controller)

    ids = [
        controller.set_power_for_address_tracked(True, "AA:BB"),
        controller.set_color_for_address_tracked(1, 2, 3, "AA:BB"),
        controller.set_brightness_for_address_tracked(50, "AA:BB"),
        controller.set_effect_for_address_tracked(4, None, "AA:BB"),
    ]
    _wait_for(results, count=4)

    assert len(set(ids)) == 4
    assert sorted(r.operation_id for r in results) == sorted(ids)
    assert all(r.code == RESULT_UNAVAILABLE for r in results)


def test_the_untracked_commands_keep_their_old_signature(controller) -> None:
    """The UI and the Local API must not start receiving results."""
    results = _collect(controller)

    assert controller.set_power_for_addresses(True, None) is None
    assert controller.set_color_for_addresses(1, 2, 3, None) is None
    assert controller.set_brightness_for_addresses(50, None) is None
    assert controller.set_effect_for_addresses(4, None, None) is None
    _wait_for(results, count=1, timeout=0.3)

    assert results == []

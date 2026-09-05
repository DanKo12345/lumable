import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import ble as module
from app.ble import BleController, ConnectionLostError


def test_write_retry_never_moves_to_a_replacement_connection():
    controller = BleController.__new__(BleController)
    replacement = SimpleNamespace(write_gatt_char=AsyncMock())

    async def fail_and_replace(*args, **kwargs):
        controller._client = replacement
        raise OSError("connection lost")

    original = SimpleNamespace(write_gatt_char=AsyncMock(side_effect=fail_and_replace))
    controller._client = original
    characteristic = SimpleNamespace(properties=["write-without-response"], uuid="fff3")
    error = asyncio.run(controller._write_to_characteristic(characteristic, b"old frame"))
    assert isinstance(error, ConnectionLostError)
    original.write_gatt_char.assert_awaited_once()
    replacement.write_gatt_char.assert_not_awaited()


@pytest.mark.parametrize("cancel_while_waiting", [False, True])
def test_reconnect_waits_for_commands_and_respects_stop(cancel_while_waiting):
    async def scenario():
        controller = BleController.__new__(BleController)
        controller._operation_lock = asyncio.Lock()
        controller._shutdown_started = False
        controller._manual_disconnect_requested = False
        controller._reconnect_delay = lambda attempt: 0
        controller._connect = AsyncMock()
        controller._restore_state_after_reconnect = AsyncMock()
        for name in ("reconnect_scheduled", "status_changed", "reconnect_succeeded"):
            setattr(controller, name, SimpleNamespace(emit=lambda *args: None))
        await controller._operation_lock.acquire()
        task = asyncio.create_task(controller._reconnect("AA"))
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            controller._connect.assert_not_awaited()
            controller._manual_disconnect_requested = cancel_while_waiting
            controller._operation_lock.release()
            await asyncio.wait_for(task, timeout=1)
            if cancel_while_waiting:
                controller._connect.assert_not_awaited()
                controller._restore_state_after_reconnect.assert_not_awaited()
            else:
                controller._connect.assert_awaited_once_with("AA", from_reconnect=True)
                controller._restore_state_after_reconnect.assert_awaited_once()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_disconnect_requested_during_connect_closes_the_late_connection():
    async def scenario():
        controller = BleController.__new__(BleController)
        controller._disconnect = AsyncMock()
        controller._scan_driver_hints = {}
        controller._shutdown_started = False
        controller._manual_disconnect_requested = False
        controller._client = None
        client = SimpleNamespace(disconnect=AsyncMock())

        async def establish(*args, **kwargs):
            controller._manual_disconnect_requested = True
            return SimpleNamespace(client=client)

        controller._establish_connection = establish
        with pytest.raises(asyncio.CancelledError):
            await controller._connect("AA")
        client.disconnect.assert_awaited_once()
        assert controller._client is None
        assert controller._manual_disconnect_requested

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [OSError("adapter gone"), asyncio.CancelledError()])
def test_failed_or_cancelled_connection_releases_the_client(monkeypatch, error):
    controller = BleController.__new__(BleController)
    device = SimpleNamespace(name="strip", address="AA")
    client = SimpleNamespace(connect=AsyncMock(side_effect=error), disconnect=AsyncMock())
    monkeypatch.setattr(module, "BleakScanner", SimpleNamespace(
        find_device_by_address=AsyncMock(return_value=device)
    ))
    monkeypatch.setattr(module, "BleakClient", lambda *args, **kwargs: client)
    with pytest.raises(type(error)):
        asyncio.run(controller._establish_connection("AA", None))
    client.disconnect.assert_awaited_once()


def test_connection_loss_is_not_reported_as_a_protocol_mismatch():
    controller = BleController.__new__(BleController)
    controller._client = SimpleNamespace(is_connected=True)
    characteristic = SimpleNamespace(uuid="fff3")
    controller._write_characteristic = characteristic
    controller._ordered_write_candidates = lambda: [characteristic]
    controller._write_to_characteristic = AsyncMock(return_value=ConnectionLostError("lost"))
    with pytest.raises(ConnectionLostError):
        asyncio.run(controller._write(b"frame", "color", stream=True))

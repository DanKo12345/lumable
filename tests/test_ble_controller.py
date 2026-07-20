from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.ble import BleController, ConnectionLostError, ProtocolCompatibilityError
from app.ble_drivers.bledom import BledomDriver


def test_exception_message_uses_fallback_for_empty_exception() -> None:
    message = BleController._exception_message(Exception())

    assert message
    assert "Exception" in message


def test_exception_message_keeps_regular_exception_text() -> None:
    assert BleController._exception_message(RuntimeError("details")) == "details"


def test_handle_future_emits_unexpected_exception_as_ble_error() -> None:
    controller = BleController.__new__(BleController)
    emitted_errors = []
    emitted_status = []

    class FakeSignal:
        def __init__(self, sink):
            self._sink = sink

        def emit(self, *args):
            self._sink.append(args)

    class FakeFuture:
        def result(self):
            raise ValueError("adapter exploded")

    controller.error_occurred = FakeSignal(emitted_errors)
    controller.status_changed = FakeSignal(emitted_status)
    controller._ble_history = []
    controller._last_ble_error = ""

    controller._handle_future(FakeFuture())

    assert emitted_errors == [("adapter exploded",)]
    assert emitted_status == [("BLE error: adapter exploded",)]
    assert controller._last_ble_error == "adapter exploded"


def test_successful_connection_can_clear_stale_ble_error() -> None:
    controller = BleController.__new__(BleController)
    controller._ble_history = []
    controller._set_last_ble_error("BLE connection was lost. Reconnecting to the last controller...")

    controller._clear_last_ble_error()

    assert controller._last_ble_error == ""
    assert controller._ble_history[-1]["event"] == "error"


def test_set_static_color_updates_cached_state_and_submits_one_operation() -> None:
    controller = BleController.__new__(BleController)
    controller._last_red = 0
    controller._last_green = 0
    controller._last_blue = 0
    controller._last_brightness = 0
    controller._driver = None
    submitted = []

    def fake_submit(coroutine) -> None:
        submitted.append(coroutine)
        coroutine.close()

    controller._submit = fake_submit

    controller.set_static_color(300, -5, 42, 150)

    assert (controller._last_red, controller._last_green, controller._last_blue) == (255, 0, 42)
    assert controller._last_brightness == 100
    assert len(submitted) == 1


def test_submit_closes_coroutine_after_shutdown_started() -> None:
    controller = BleController.__new__(BleController)
    controller._shutdown_started = True
    controller._loop = asyncio.new_event_loop()

    async def sample() -> None:
        await asyncio.sleep(0)

    coroutine = sample()
    controller._submit(coroutine)

    assert coroutine.cr_frame is None
    controller._loop.close()


def test_run_serialized_closes_coroutine_cancelled_before_start() -> None:
    async def scenario() -> None:
        controller = BleController.__new__(BleController)
        controller._operation_lock = asyncio.Lock()
        await controller._operation_lock.acquire()

        async def sample() -> None:
            await asyncio.sleep(0)

        coroutine = sample()
        task = asyncio.create_task(controller._run_serialized(coroutine))
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        controller._operation_lock.release()
        assert coroutine.cr_frame is None

    asyncio.run(scenario())


def test_set_static_color_still_sends_color_when_brightness_fails() -> None:
    controller = BleController.__new__(BleController)

    controller._set_brightness = AsyncMock(side_effect=RuntimeError("brightness failed"))
    controller._set_color = AsyncMock()

    asyncio.run(controller._set_static_color(10, 20, 30, 100))

    controller._set_brightness.assert_awaited_once_with(100)
    controller._set_color.assert_awaited_once_with(10, 20, 30)


def test_set_static_color_keeps_color_error_visible() -> None:
    controller = BleController.__new__(BleController)

    controller._set_brightness = AsyncMock()
    controller._set_color = AsyncMock(side_effect=RuntimeError("color failed"))

    with pytest.raises(RuntimeError, match="color failed"):
        asyncio.run(controller._set_static_color(10, 20, 30, 100))

    controller._set_brightness.assert_awaited_once_with(100)
    controller._set_color.assert_awaited_once_with(10, 20, 30)


def test_write_many_remembers_successful_payload_variant() -> None:
    controller = BleController.__new__(BleController)
    controller._client = object()
    controller._write_characteristic = object()
    controller._preferred_payload_indices = {}
    calls = []

    async def fake_write(payload: bytes, _description: str, **_kwargs) -> None:
        calls.append(payload)
        if payload == b"primary":
            raise RuntimeError("primary failed")

    controller._write = fake_write

    class FakeDriver:
        id = "fake"

    controller._driver = FakeDriver()
    payloads = [b"primary", b"fallback"]

    asyncio.run(controller._write_many(payloads, "test"))
    asyncio.run(controller._write_many(payloads, "test"))

    assert calls == [b"primary", b"fallback", b"fallback"]


def test_write_many_does_not_share_cache_between_payload_shapes() -> None:
    controller = BleController.__new__(BleController)
    controller._client = object()
    controller._write_characteristic = object()
    controller._preferred_payload_indices = {}
    calls = []

    async def fake_write(payload: bytes, _description: str, **_kwargs) -> None:
        calls.append(payload)
        if payload in {bytes.fromhex("7e 00 01 32 00 00 00 00 ef"), bytes.fromhex("7e 00 05 03 01 02 03 00 ef")}:
            raise RuntimeError("primary failed")

    controller._write = fake_write

    class FakeDriver:
        id = "bledom"

    controller._driver = FakeDriver()
    brightness_payloads = [
        bytes.fromhex("7e 00 01 32 00 00 00 00 ef"),
        bytes.fromhex("56 00 00 00 80 0f aa"),
    ]
    color_payloads = [
        bytes.fromhex("7e 00 05 03 01 02 03 00 ef"),
        bytes.fromhex("56 01 02 03 00 f0 aa"),
    ]

    asyncio.run(controller._write_many(brightness_payloads, "brightness"))
    asyncio.run(controller._write_many(color_payloads, "color"))

    assert calls == [
        bytes.fromhex("7e 00 01 32 00 00 00 00 ef"),
        bytes.fromhex("56 00 00 00 80 0f aa"),
        bytes.fromhex("7e 00 05 03 01 02 03 00 ef"),
        bytes.fromhex("56 01 02 03 00 f0 aa"),
    ]


def test_set_effect_with_speed_skips_missing_speed_payload() -> None:
    controller = BleController.__new__(BleController)
    calls = []

    class FakeDriver:
        def effect_payload(self, code: int) -> bytes | None:
            return b"effect" if code == 0x25 else None

        def speed_payload(self, _value: int) -> bytes | None:
            return None

    async def fake_write(payload: bytes, _description: str, **_kwargs) -> None:
        calls.append(payload)

    controller._driver = FakeDriver()
    controller._write = fake_write

    asyncio.run(controller._set_effect_with_speed(0x25, 60))

    # Effect is sent then re-sent once (BLEDOM switch-reliability nudge); no
    # speed command because speed_payload returns None.
    assert calls == [b"effect", b"effect"]


def test_set_effect_with_speed_uses_combined_effect_payload() -> None:
    controller = BleController.__new__(BleController)
    controller._current_effect_code = 0
    calls = []

    class FakeDriver:
        def effect_payload(self, code: int) -> bytes | None:
            return b"default" if code == 0x25 else None

        def effect_payload_with_speed(self, code: int, speed: int) -> bytes | None:
            return f"effect-{code:02x}-{speed}".encode()

        def speed_payload(self, _value: int) -> bytes | None:
            return None

    async def fake_write(payload: bytes, _description: str, **_kwargs) -> None:
        calls.append(payload)

    controller._driver = FakeDriver()
    controller._write = fake_write

    asyncio.run(controller._set_effect_with_speed(0x25, 60))

    assert calls == [b"effect-25-60"]
    assert controller._current_effect_code == 0x25


def test_set_effect_speed_reuses_current_combined_effect_payload() -> None:
    controller = BleController.__new__(BleController)
    controller._current_effect_code = 0x25
    calls = []

    class FakeDriver:
        def effect_payload(self, code: int) -> bytes | None:
            return b"default" if code == 0x25 else None

        def effect_payload_with_speed(self, code: int, speed: int) -> bytes | None:
            return f"effect-{code:02x}-{speed}".encode()

        def speed_payload(self, _value: int) -> bytes | None:
            return None

    async def fake_write(payload: bytes, _description: str, **_kwargs) -> None:
        calls.append(payload)

    controller._driver = FakeDriver()
    controller._write = fake_write

    asyncio.run(controller._set_effect_speed(25))

    assert calls == [b"effect-25-25"]


def test_bledom_write_many_stops_after_primary_payload_success() -> None:
    controller = BleController.__new__(BleController)
    controller._client = object()
    controller._write_characteristic = object()
    controller._preferred_payload_indices = {}
    controller._driver = BledomDriver()
    calls = []

    async def fake_write(payload: bytes, _description: str, **_kwargs) -> None:
        calls.append(payload)

    controller._write = fake_write

    asyncio.run(controller._write_many(controller._driver.power_payloads(True), "power"))

    assert calls == [bytes.fromhex("7e 00 04 f0 00 01 ff 00 ef")]


def test_bledom_write_many_remembers_alt_payload_when_primary_fails() -> None:
    controller = BleController.__new__(BleController)
    controller._client = object()
    controller._write_characteristic = object()
    controller._preferred_payload_indices = {}
    controller._driver = BledomDriver()
    calls = []
    primary = bytes.fromhex("7e 00 04 f0 00 01 ff 00 ef")
    alt = bytes.fromhex("cc 23 33")

    async def fake_write(payload: bytes, _description: str, **_kwargs) -> None:
        calls.append(payload)
        if payload == primary:
            raise RuntimeError("primary failed")

    controller._write = fake_write

    payloads = controller._driver.power_payloads(True)
    asyncio.run(controller._write_many(payloads, "power"))
    asyncio.run(controller._write_many(payloads, "power"))

    assert calls == [primary, alt, alt]


def test_bledom_driver_variant_is_remembered_after_successful_write_many() -> None:
    controller = BleController.__new__(BleController)
    controller._client = object()
    controller._write_characteristic = object()
    controller._preferred_payload_indices = {}
    controller._driver = BledomDriver()

    async def fake_write(_payload: bytes, _description: str, **_kwargs) -> None:
        return None

    controller._write = fake_write

    asyncio.run(controller._write_many(controller._driver.power_payloads(True), "power"))

    assert controller._driver.power_payloads(False) == [bytes.fromhex("7e 00 04 00 00 00 ff 00 ef")]
    assert controller._driver.color_payloads(1, 2, 3) == [
        bytes.fromhex("7e 00 05 03 01 02 03 00 ef"),
        bytes.fromhex("56 01 02 03 00 f0 aa"),
    ]


def test_protocol_mismatch_diagnostic_includes_controller_details() -> None:
    controller = BleController.__new__(BleController)

    class FakeDevice:
        name = "ELK-BLEDOM-Clone"
        address = "AA:BB:CC"
        rssi = -52

    class FakeDriver:
        id = "bledom"
        display_name = "BLEDOM / ELK-BLEDOM"
        effects = ()

        def brightness_payloads(self, _value: int) -> list[bytes]:
            return []

        def speed_payload(self, _value: int) -> bytes | None:
            return None

    class FakeCharacteristic:
        uuid = "0000fff3-0000-1000-8000-00805f9b34fb"
        properties = ["write-without-response"]

    class FakeClient:
        is_connected = True

    controller._client = FakeClient()
    controller._device = FakeDevice()
    controller._driver = FakeDriver()
    controller._write_characteristic = FakeCharacteristic()
    controller._write_characteristics = [FakeCharacteristic()]

    diagnostic = controller._protocol_mismatch_diagnostic([b"\x7e\x00\x04"])

    assert "protocol differs" in diagnostic
    assert "ELK-BLEDOM-Clone" in diagnostic
    assert "AA:BB:CC" in diagnostic
    assert "BLEDOM / ELK-BLEDOM" in diagnostic
    assert "0000fff3-0000-1000-8000-00805f9b34fb" in diagnostic
    assert "7e 00 04" in diagnostic


def test_protocol_detection_diagnostic_includes_services_and_hint() -> None:
    controller = BleController.__new__(BleController)

    class FakeDevice:
        name = "Mystery LED"
        address = "AA:BB:CC"

    class FakeCharacteristic:
        uuid = "0000abcd-0000-1000-8000-00805f9b34fb"
        properties = ["notify"]

    class FakeService:
        uuid = "0000feed-0000-1000-8000-00805f9b34fb"
        characteristics = [FakeCharacteristic()]

    diagnostic = controller._protocol_detection_diagnostic(FakeDevice(), [FakeService()], "bledom")

    assert "protocol differs" in diagnostic
    assert "Mystery LED" in diagnostic
    assert "AA:BB:CC" in diagnostic
    assert "bledom" in diagnostic
    assert "0000feed-0000-1000-8000-00805f9b34fb" in diagnostic
    assert "0000abcd-0000-1000-8000-00805f9b34fb" in diagnostic


def test_write_many_raises_protocol_compatibility_error_after_all_variants_fail() -> None:
    controller = BleController.__new__(BleController)
    controller._client = object()
    controller._write_characteristic = object()
    controller._preferred_payload_indices = {}
    emitted = []

    class FakeDriver:
        id = "fake"

    class FakeSignal:
        def emit(self, message: str) -> None:
            emitted.append(message)

    async def fake_write(_payload: bytes, _description: str, **_kwargs) -> None:
        raise ProtocolCompatibilityError("nope")

    controller._driver = FakeDriver()
    controller._write = fake_write
    controller.status_changed = FakeSignal()
    controller._ble_history = []
    controller._last_ble_error = ""
    controller._protocol_mismatch_diagnostic = lambda _payloads: "Device was found and matched a known controller family, but the command protocol differs."

    with pytest.raises(ProtocolCompatibilityError, match="protocol differs"):
        asyncio.run(controller._write_many([b"one", b"two"], "test"))

    assert emitted == ["Device was found and matched a known controller family, but the command protocol differs."]
    assert controller._last_ble_error == "Device was found and matched a known controller family, but the command protocol differs."
    assert controller._ble_history[-1]["event"] == "protocol_mismatch"


def test_write_retries_transient_failures_before_success() -> None:
    controller = BleController.__new__(BleController)
    emitted = []
    calls = []

    class FakeSignal:
        def emit(self, *args) -> None:
            emitted.append(args)

    class FakeCharacteristic:
        uuid = "fff3"
        properties = ["write-without-response"]

    class FakeClient:
        async def write_gatt_char(self, characteristic, payload: bytes, *, response: bool) -> None:
            calls.append((str(characteristic.uuid), payload, response))
            if len(calls) <= 2:
                raise RuntimeError("temporary write failure")

    controller._client = FakeClient()
    controller._write_characteristic = FakeCharacteristic()
    controller._write_characteristics = [FakeCharacteristic()]
    controller.status_changed = FakeSignal()
    controller._ble_history = []
    controller._last_ble_error = ""

    asyncio.run(controller._write(b"payload", "description"))

    assert len(calls) == 3
    assert any("__L10N__" in args[0] and "write_retry" in args[0] for args in emitted)
    assert emitted[-1] == ("description (70 61 79 6c 6f 61 64) -> fff3",)
    assert controller._ble_history[0]["event"] == "retry"
    assert controller._ble_history[-1] == {
        "event": "command",
        "description": "description",
        "payload": "70 61 79 6c 6f 61 64",
        "targets": "fff3",
    }


def test_write_starts_reconnect_when_client_is_already_disconnected() -> None:
    async def scenario() -> None:
        controller = BleController.__new__(BleController)
        emitted_status = []
        emitted_connected = []
        reconnects = []

        class FakeSignal:
            def __init__(self, target: list) -> None:
                self._target = target

            def emit(self, *args) -> None:
                self._target.append(args)

        class FakeClient:
            is_connected = False

        class FakeCharacteristic:
            uuid = "fff3"
            properties = ["write-without-response"]

        class FakeDevice:
            name = "ELK-BLEDOM"
            address = "AA:BB:CC"

        async def fake_reconnect(address: str) -> None:
            reconnects.append(address)

        controller._loop = asyncio.get_running_loop()
        controller._shutdown_started = False
        controller._manual_disconnect_requested = False
        controller._client = FakeClient()
        controller._device = FakeDevice()
        controller._driver = object()
        controller._write_characteristic = FakeCharacteristic()
        controller._write_characteristics = [FakeCharacteristic()]
        controller._preferred_payload_indices = {}
        controller._reconnect_address = ""
        controller._reconnect_task = None
        controller._reconnect = fake_reconnect
        controller.status_changed = FakeSignal(emitted_status)
        controller.connected_changed = FakeSignal(emitted_connected)

        with pytest.raises(ConnectionLostError, match="Reconnecting"):
            await controller._write(b"payload", "description")
        await controller._reconnect_task

        assert controller._client is None
        assert emitted_connected == [(False, "")]
        assert reconnects == ["AA:BB:CC"]
        assert any("__L10N__" in args[0] and "unexpected_disconnect" in args[0] for args in emitted_status)

    asyncio.run(scenario())


def test_write_attempt_handles_client_cleared_during_disconnect() -> None:
    controller = BleController.__new__(BleController)
    controller._client = None

    class FakeCharacteristic:
        uuid = "fff3"
        properties = ["write-without-response"]

    error = asyncio.run(controller._write_attempt(FakeCharacteristic(), b"payload", response=False))

    assert isinstance(error, ConnectionLostError)
    assert "Reconnecting" in str(error)


def test_write_many_preserves_connection_lost_error() -> None:
    controller = BleController.__new__(BleController)
    controller._client = object()
    controller._write_characteristic = object()
    controller._preferred_payload_indices = {}

    class FakeDriver:
        id = "fake"

    async def fake_write(_payload: bytes, _description: str, **_kwargs) -> None:
        raise ConnectionLostError("BLE connection was lost. Reconnecting to the last controller...")

    controller._driver = FakeDriver()
    controller._write = fake_write

    with pytest.raises(ConnectionLostError, match="Reconnecting"):
        asyncio.run(controller._write_many([b"one", b"two"], "test"))


def test_unexpected_disconnect_clears_state_and_schedules_reconnect() -> None:
    async def scenario() -> None:
        controller = BleController.__new__(BleController)
        emitted_status = []
        emitted_connected = []
        reconnects = []

        class FakeSignal:
            def __init__(self, target: list) -> None:
                self._target = target

            def emit(self, *args) -> None:
                self._target.append(args)

        class FakeClient:
            pass

        class FakeDevice:
            name = "ELK-BLEDOM"
            address = "AA:BB:CC"

        async def fake_reconnect(address: str) -> None:
            reconnects.append(address)

        client = FakeClient()
        controller._loop = asyncio.get_running_loop()
        controller._shutdown_started = False
        controller._manual_disconnect_requested = False
        controller._client = client
        controller._device = FakeDevice()
        controller._driver = object()
        controller._write_characteristic = object()
        controller._write_characteristics = [object()]
        controller._preferred_payload_indices = {("x", ()): 0}
        controller._reconnect_address = ""
        controller._reconnect_task = None
        controller._reconnect = fake_reconnect
        controller.status_changed = FakeSignal(emitted_status)
        controller.connected_changed = FakeSignal(emitted_connected)

        controller._on_unexpected_disconnect(client)
        await controller._reconnect_task

        assert controller._client is None
        assert controller._driver is None
        assert controller._write_characteristics == []
        assert emitted_connected == [(False, "")]
        assert reconnects == ["AA:BB:CC"]
        assert any("__L10N__" in args[0] and "unexpected_disconnect" in args[0] for args in emitted_status)

    asyncio.run(scenario())


def test_ordered_write_candidates_skips_notify_and_prefers_selected() -> None:
    controller = BleController.__new__(BleController)

    class FakeCharacteristic:
        def __init__(self, uuid: str, properties: list[str]) -> None:
            self.uuid = uuid
            self.properties = properties

    notify = FakeCharacteristic("fff4", ["notify"])
    write = FakeCharacteristic("fff3", ["write-without-response", "read"])
    other_write = FakeCharacteristic("ffe9", ["write"])

    controller._write_characteristic = write
    controller._write_characteristics = [notify, other_write, write]

    assert controller._ordered_write_candidates() == [write, other_write]


def _promote_scenario_controller() -> tuple:
    """Build a controller with one live primary and two mirrors."""
    from app.ble import DeviceConnection

    controller = BleController.__new__(BleController)
    sinks: dict[str, list] = {"status": [], "mirrors": [], "primary": []}

    class FakeSignal:
        def __init__(self, target: list) -> None:
            self._target = target

        def emit(self, *args) -> None:
            self._target.append(args)

    class FakeClient:
        def __init__(self, tag: str) -> None:
            self.tag = tag
            self.is_connected = True

    class FakeDevice:
        def __init__(self, name: str, address: str) -> None:
            self.name = name
            self.address = address

    controller._client = FakeClient("primary")
    controller._device = FakeDevice("Desk", "AA:BB:CC")
    controller._driver = object()
    controller._write_characteristic = "char-primary"
    controller._write_characteristics = ["char-primary"]
    controller._preferred_payload_indices = {"a": 0}
    controller._pacer = "pacer-primary"
    controller._reconnect_address = "AA:BB:CC"
    controller._mirror_connections = [
        DeviceConnection(
            address="DD:EE:FF",
            client=FakeClient("tv"),
            device=FakeDevice("TV", "DD:EE:FF"),
            driver=object(),
            write_characteristic="char-tv",
            write_characteristics=["char-tv"],
            preferred_payload_indices={"b": 1},
        ),
        DeviceConnection(
            address="11:22:33",
            client=FakeClient("bed"),
            device=FakeDevice("Bed", "11:22:33"),
            driver=object(),
            write_characteristic="char-bed",
            write_characteristics=["char-bed"],
            preferred_payload_indices={"c": 2},
        ),
    ]
    controller.status_changed = FakeSignal(sinks["status"])
    controller.mirrors_changed = FakeSignal(sinks["mirrors"])
    controller.primary_changed = FakeSignal(sinks["primary"])
    return controller, sinks


def test_promote_mirror_swaps_roles_without_reconnecting() -> None:
    async def scenario() -> None:
        controller, sinks = _promote_scenario_controller()
        old_primary_client = controller._client

        await controller._promote_mirror("DD:EE:FF")

        # The promoted mirror is now the primary, with all of its own handles.
        assert controller._device.address == "DD:EE:FF"
        assert controller._client.tag == "tv"
        assert controller._write_characteristic == "char-tv"
        assert controller._write_characteristics == ["char-tv"]
        assert controller._preferred_payload_indices == {"b": 1}
        # The old primary became a mirror; nothing was disconnected.
        assert controller.mirror_addresses() == ["11:22:33", "AA:BB:CC"]
        assert old_primary_client.is_connected is True
        assert controller._client.is_connected is True
        # Reconnect must now chase the new main strip.
        assert controller._reconnect_address == "DD:EE:FF"
        assert sinks["primary"] == [("DD:EE:FF", "TV")]
        assert sinks["mirrors"] == [(["11:22:33", "AA:BB:CC"],)]
        assert any("primary_changed" in args[0] for args in sinks["status"])

    asyncio.run(scenario())


def test_promote_mirror_keeps_the_old_primary_pacer_with_its_connection() -> None:
    async def scenario() -> None:
        controller, _ = _promote_scenario_controller()

        await controller._promote_mirror("DD:EE:FF")

        parked = [conn for conn in controller._mirror_connections if conn.address == "AA:BB:CC"]
        assert len(parked) == 1
        # Pacing state travels with the connection, not with the "primary" role.
        assert parked[0].pacer == "pacer-primary"
        assert controller._pacer != "pacer-primary"

    asyncio.run(scenario())


def test_promote_mirror_ignores_unknown_or_current_address() -> None:
    async def scenario() -> None:
        for address in ("DE:AD:BE", "AA:BB:CC", ""):
            controller, sinks = _promote_scenario_controller()

            await controller._promote_mirror(address)

            assert controller._device.address == "AA:BB:CC"
            assert controller._reconnect_address == "AA:BB:CC"
            assert sinks["primary"] == []
            assert sinks["mirrors"] == []

    asyncio.run(scenario())


def test_promote_mirror_does_nothing_without_a_live_primary() -> None:
    async def scenario() -> None:
        controller, sinks = _promote_scenario_controller()
        controller._client = None

        await controller._promote_mirror("DD:EE:FF")

        assert sinks["primary"] == []
        assert len(controller._mirror_connections) == 2

    asyncio.run(scenario())

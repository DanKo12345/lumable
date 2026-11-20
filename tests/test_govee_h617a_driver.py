from __future__ import annotations

import asyncio
from functools import reduce
from operator import xor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from app import ble as ble_module
from app.ble import NO_TARGET, BleController, ConnectionLostError, DeviceConnection
from app.ble_drivers import DRIVERS, detect_connected_driver, detect_scan_driver, probe_driver_candidates
from app.ble_drivers.bledom import TARGET_SERVICE_UUID, BledomDriver
from app.ble_drivers.govee_h617a import GOVEE_CONTROL_UUID, GoveeH617ADriver
from app.ble_drivers.triones import TrionesDriver
from app.driver_capabilities import capabilities_for
from app.scan_observations import ScanObservations

ADDRESS = "AA:BB:CC:DD:EE:01"
NAME = "Govee_H617A_1234"


def _characteristic(uuid=GOVEE_CONTROL_UUID, properties=("write-without-response",)):
    return SimpleNamespace(uuid=uuid, properties=properties)


def _services(*characteristics, uuid="00010203-0405-0607-0809-0a0b0c0d1910"):
    return [SimpleNamespace(uuid=uuid, characteristics=characteristics)]


@pytest.mark.parametrize("name", [NAME, "govee_h617a_abcd", "Govee H617A"])
def test_scan_detects_h617a_by_model_name(name):
    assert isinstance(detect_scan_driver(name, ()), GoveeH617ADriver)


@pytest.mark.parametrize("name", ["", "H617A", "Govee_H617A0_1234", "Govee_H617C_1234", "Govee_H617E_1234"])
def test_other_devices_are_not_claimed_or_suggested_by_shared_govee_uuid(name):
    services = _services(_characteristic())
    assert detect_scan_driver(name, [GOVEE_CONTROL_UUID]) is None
    assert detect_connected_driver(name, services, preferred_id="govee_h617a") is None
    assert not probe_driver_candidates(name, services)


@pytest.mark.parametrize("properties", [("notify",), ("write",)])
def test_named_h617a_requires_the_correct_characteristic_and_write_mode(properties):
    services = _services(
        _characteristic(properties=properties),
        _characteristic(uuid="0000fff3-0000-1000-8000-00805f9b34fb"),
        uuid=TARGET_SERVICE_UUID,
    )
    assert detect_connected_driver(NAME, services, preferred_id="bledom") is None
    assert not probe_driver_candidates(NAME, services)


def test_only_the_govee_control_characteristic_is_used():
    driver = GoveeH617ADriver()
    control = _characteristic(uuid=GOVEE_CONTROL_UUID.upper())
    other_write = _characteristic(uuid="0000fff3-0000-1000-8000-00805f9b34fb")
    services = _services(other_write, control, uuid=TARGET_SERVICE_UUID)
    assert isinstance(detect_connected_driver(NAME, services, preferred_id="bledom"), GoveeH617ADriver)
    assert driver.pick_write_characteristic(services) is control
    assert driver.collect_write_characteristics(services) == [control]


def test_packets_match_captured_h617a_commands():
    driver = GoveeH617ADriver()
    assert driver.power_payloads(True) == [bytes.fromhex("3301010000000000000000000000000000000033")]
    assert driver.power_payloads(False) == [bytes.fromhex("3301000000000000000000000000000000000032")]
    assert driver.brightness_payloads(50) == [bytes.fromhex("3304320000000000000000000000000000000005")]
    assert driver.brightness_payloads(101) == [bytes.fromhex("3304640000000000000000000000000000000053")]
    assert driver.brightness_payloads(0)[0][2] == 1
    assert driver.color_payloads(256, -1, 0) == [bytes.fromhex("33051501ff00000000000000ff7f00000000005d")]
    assert driver.color_payloads(0, 0, 255) == [bytes.fromhex("330515010000ff0000000000ff7f00000000005d")]


def test_h617a_exposes_captured_scenes_without_claiming_segment_control():
    controller = BleController.__new__(BleController)
    controller._driver = GoveeH617ADriver()
    presets = controller.effect_presets()
    assert len(presets) == 35
    assert presets[0].key == "static_color"
    assert controller.supports_effect_code(0xC2)
    assert not controller.supports_effect_speed()
    assert capabilities_for(controller._driver.id) == {
        "rgb": True, "rgbw": False, "cct": False, "firmware_effects": True, "segments": False,
    }


def test_all_captured_scenes_have_complete_frames_and_disjoint_app_codes():
    driver = GoveeH617ADriver()
    for preset in driver.effects[1:]:
        sequence = driver.effect_sequence(preset.code)
        assert sequence is not None
        assert sequence.interval_seconds == 0.05
        assert all(len(frame) == 20 and reduce(xor, frame) == 0 for frame in sequence.frames)
        assert sequence.frames[-1][:3] == bytes.fromhex("33 05 04")
        fragments = sequence.frames[:-1]
        if fragments:
            assert all(frame[0] == 0xA3 for frame in fragments)
            assert [frame[1] for frame in fragments] == [*range(len(fragments) - 1), 0xFF]
            assert fragments[0][3] == len(fragments)
        for other in DRIVERS:
            if other.id != driver.id:
                assert other.effect_payload(preset.code) is None
                assert other.effect_sequence(preset.code) is None

    assert driver.effect_sequence(0xC0).frames == (bytes.fromhex("3305040000000000000000000000000000000032"),)
    forest = driver.effect_sequence(0xC2).frames
    assert len(forest) == 8
    assert forest[0] == bytes.fromhex("a30001070203260001000a0201ff1901b40a0ad9")
    assert forest[-1] == bytes.fromhex("3305047308000000000000000000000000000049")


def test_scan_to_connection_retains_model_and_writes_only_to_its_control_uuid(monkeypatch):
    async def scenario():
        controller = BleController()
        try:
            device = SimpleNamespace(name=None, address=ADDRESS)
            seen = ScanObservations()
            for local_name in (None, NAME, None):
                seen.observe(device, SimpleNamespace(local_name=local_name, rssi=-55))
            monkeypatch.setattr(controller, "_listen_for_advertisements", AsyncMock(return_value=seen))
            await controller._scan()
            assert controller._last_scan_results[0]["supported"] is True
            assert controller._last_scan_results[0]["driver"] == "Govee H617A"

            control = _characteristic()
            client = SimpleNamespace(
                is_connected=True, connect=AsyncMock(), disconnect=AsyncMock(), write_gatt_char=AsyncMock(),
                services=_services(_characteristic(uuid="other"), control),
            )
            monkeypatch.setattr(ble_module, "BleakClient", lambda *_args, **_kwargs: client)
            monkeypatch.setattr(ble_module.BleakScanner, "find_device_by_address", AsyncMock(return_value=device))
            await controller._connect(ADDRESS)
            client.write_gatt_char.assert_not_called()
            await controller._set_color_stream(0, 0, 255)
            await controller._disconnect()
            client.write_gatt_char.assert_awaited_once_with(
                control, bytes.fromhex("330515010000ff0000000000ff7f00000000005d"), response=False,
            )
        finally:
            controller.shutdown()

    asyncio.run(scenario())


def _fake_connection(driver, address=ADDRESS):
    return DeviceConnection(
        address=address,
        client=SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock()),
        device=SimpleNamespace(address=address, name=NAME),
        driver=driver,
        write_characteristic=_characteristic(),
    )


def _test_controller(primary):
    controller = BleController.__new__(BleController)
    controller._client = primary.client
    controller._device = primary.device
    controller._driver = primary.driver
    controller._write_characteristic = primary.write_characteristic
    controller._write_characteristics = []
    controller._mirror_connections = []
    controller._current_effect_code = 0
    controller._preferred_payload_indices = {}
    controller.status_changed = SimpleNamespace(emit=Mock())
    return controller


def test_scene_batch_is_serialized_with_brightness_and_stream_writes():
    async def scenario():
        primary = _fake_connection(GoveeH617ADriver())
        controller = _test_controller(primary)
        controller._operation_lock = asyncio.Lock()
        frames = primary.driver.effect_sequence(0xC2).frames
        first_started, allow_batch = asyncio.Event(), asyncio.Event()

        async def write(_characteristic, payload, *, response):
            if payload == frames[0]:
                first_started.set()
                await allow_batch.wait()

        primary.client.write_gatt_char.side_effect = write
        batch = asyncio.create_task(controller._run_serialized(controller._set_effect_with_speed(0xC2, 50)))
        try:
            await asyncio.wait_for(first_started.wait(), 2)
            brightness = asyncio.create_task(controller._run_serialized(controller._set_brightness(3)))
            stream = asyncio.create_task(controller._run_serialized(controller._set_color_stream(1, 2, 3)))
            await asyncio.sleep(0)
            assert primary.client.write_gatt_char.await_count == 1
            allow_batch.set()
            await asyncio.wait_for(asyncio.gather(batch, brightness, stream), 3)
        finally:
            allow_batch.set()
            await batch
        expected = [*frames, *primary.driver.brightness_payloads(3), *primary.driver.color_payloads(1, 2, 3)]
        assert primary.client.write_gatt_char.await_args_list == [
            call(primary.write_characteristic, frame, response=False) for frame in expected
        ]
        assert controller._current_effect_code == 0

    asyncio.run(scenario())


def test_a_failed_fragment_never_activates_scene_or_changes_cached_effect():
    primary = _fake_connection(GoveeH617ADriver())
    controller = _test_controller(primary)
    controller._current_effect_code = 0xC0
    primary.client.write_gatt_char.side_effect = [None, OSError("radio lost")]
    with pytest.raises(OSError, match="radio lost"):
        asyncio.run(controller._set_effect(0xC2))
    assert primary.client.write_gatt_char.await_count == 2
    assert controller._current_effect_code == 0xC0
    assert controller._ble_history[-1]["event"] == "effect_upload_failed"
    controller.status_changed.emit.assert_not_called()


def test_an_effect_upload_never_switches_to_a_new_connection():
    primary = _fake_connection(GoveeH617ADriver())
    replacement = _fake_connection(GoveeH617ADriver())
    controller = _test_controller(primary)

    async def replace(*_args, **_kwargs):
        controller._client = replacement.client

    primary.client.write_gatt_char.side_effect = replace
    with pytest.raises(ConnectionLostError):
        asyncio.run(controller._set_effect(0xC2))
    assert primary.client.write_gatt_char.await_count == 1
    replacement.client.write_gatt_char.assert_not_awaited()
    assert controller._current_effect_code == 0


def test_addressed_effect_only_writes_a_compatible_target_and_requires_the_whole_batch():
    legacy = _fake_connection(BledomDriver())
    controller = _test_controller(legacy)
    mirror = _fake_connection(GoveeH617ADriver(), "AA:BB:CC:DD:EE:02")
    controller._mirror_connections = [mirror]
    assert asyncio.run(controller._set_effect_for_addresses(0xC2, 50, [legacy.address])) is NO_TARGET
    assert asyncio.run(controller._set_effect_for_addresses(0xC2, 50, [mirror.address])) is None
    assert mirror.client.write_gatt_char.await_count == len(mirror.driver.effect_sequence(0xC2).frames)
    assert controller._current_effect_code == 0
    legacy.client.write_gatt_char.assert_not_awaited()

    mirror.client.write_gatt_char.reset_mock()
    mirror.client.write_gatt_char.side_effect = [None, OSError("radio lost")]
    assert asyncio.run(controller._set_effect_for_addresses(0xC2, None, [mirror.address])) is NO_TARGET
    assert mirror.client.write_gatt_char.await_count == 2


def test_static_mode_replaces_a_govee_effect_with_the_last_solid_color():
    primary = _fake_connection(GoveeH617ADriver())
    controller = _test_controller(primary)
    controller._last_red, controller._last_green, controller._last_blue = 1, 2, 3
    controller._current_effect_code = 0xC2
    asyncio.run(controller._set_effect(0))
    primary.client.write_gatt_char.assert_awaited_once_with(
        primary.write_characteristic, primary.driver.color_payloads(1, 2, 3)[0], response=False,
    )
    assert controller._current_effect_code == 0


@pytest.mark.parametrize("reconnect", [False, True])
def test_power_resume_restores_the_govee_effect_once_instead_of_solid_color(reconnect):
    primary = _fake_connection(GoveeH617ADriver())
    controller = _test_controller(primary)
    controller._current_effect_code = 0xC2
    controller._desired_power_on = True
    controller._last_brightness = 3
    if reconnect:
        asyncio.run(controller._restore_state_after_reconnect())
    else:
        asyncio.run(controller._set_power(True))
    expected = [
        *primary.driver.power_payloads(True),
        *primary.driver.brightness_payloads(3),
        *primary.driver.effect_sequence(0xC2).frames,
    ]
    assert primary.client.write_gatt_char.await_args_list == [
        call(primary.write_characteristic, frame, response=False) for frame in expected
    ]
    assert controller._current_effect_code == 0xC2


def test_power_resume_does_not_try_to_write_an_empty_triones_brightness_command():
    primary = _fake_connection(TrionesDriver())
    controller = _test_controller(primary)
    controller._last_red, controller._last_green, controller._last_blue = 10, 20, 30
    controller._last_brightness = 50
    asyncio.run(controller._set_power(True))
    expected = [*primary.driver.power_payloads(True), *primary.driver.color_payloads(10, 20, 30)]
    assert primary.client.write_gatt_char.await_args_list == [
        call(primary.write_characteristic, frame, response=False) for frame in expected
    ]


def test_real_window_lists_govee_effects_and_can_change_brightness_without_stopping_them(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from app.local_api.backend import QtApiBackend
    from app.main_window import MainWindow
    from app.quick_modes import QUICK_MODE_MAP

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        monkeypatch.setattr("app.color_controller.can_use", lambda _feature: False)
        monkeypatch.setattr("app.color_controller.free_effect_limit", lambda: 12)
        window._ble._driver = GoveeH617ADriver()
        window._is_connected = True
        with window._suppress_signals():
            window.brightness_slider.setValue(0)
        window._refresh_effect_names()
        assert window.brightness_slider.minimum() == window.brightness_slider.value() == 1
        assert window.effect_combo.count() == 35
        assert window.effect_combo.findData(0xE1) == -1  # the existing Free effect limit still applies
        assert window.effect_combo.findData(0xCB) >= 0
        assert window._quick_mode_effect_code(QUICK_MODE_MAP["rainbow"]) == 0xCB

        order = []
        monkeypatch.setattr(window, "stop_streams", lambda: order.append("streams stopped"))
        monkeypatch.setattr(window._ble, "set_effect", lambda code: order.append(("effect", code)))
        monkeypatch.setattr(window._ble, "set_brightness", lambda value: order.append(("brightness", value)))
        window.effect_combo.setCurrentIndex(window.effect_combo.findData(0xC2))
        window._effect_debounce.stop()
        window._apply_selected_effect()
        assert order == ["streams stopped", ("effect", 0xC2)]
        assert window.speed_slider.isHidden()
        assert window.speed_value.isHidden()

        window.brightness_slider.setValue(3)
        window._color_apply_debounce.stop()
        window._apply_queued_color_update()
        assert order[-1] == ("brightness", 3)
        assert window.effect_combo.currentData() == 0xC2

        backend = QtApiBackend(window)
        backend.set_effect(0xCB, 50, None)
        backend.set_brightness(7, None)
        assert order[-3:] == ["streams stopped", ("effect", 0xCB), ("brightness", 7)]
        assert backend.status()["effect"] == {"kind": "firmware", "ref": 0xCB, "speed": None}
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()

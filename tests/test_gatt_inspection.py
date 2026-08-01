"""Checking an unrecognised device without touching it.

The whole value of this path is what it does *not* do. The fake client below
fails the test on any write, and the controller's own connection state is
asserted untouched, because a device we do not understand must not have a
guessed protocol tried on it.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from app.ble import BleController


class _WriteAttempted(AssertionError):
    """Raised by the fake device if anything tries to write to it."""


class _Characteristic:
    def __init__(self, uuid, properties):
        self.uuid = uuid
        self.properties = properties


class _Service:
    def __init__(self, uuid, characteristics):
        self.uuid = uuid
        self.characteristics = characteristics


class _FakeClient:
    """A device that reports its services and refuses to be written to."""

    instances: list = []

    def __init__(self, address, **kwargs):
        self.address = address
        self.connected = False
        self.disconnected = False
        _FakeClient.instances.append(self)
        self.services = [
            _Service(
                "0000FFF0-0000-1000-8000-00805F9B34FB",
                [
                    _Characteristic("0000FFF3-0000-1000-8000-00805F9B34FB", ["write-without-response"]),
                    _Characteristic("0000FFF4-0000-1000-8000-00805F9B34FB", ["notify"]),
                ],
            )
        ]

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def write_gatt_char(self, *args, **kwargs):
        raise _WriteAttempted("a compatibility check must never write to the device")

    async def read_gatt_char(self, *args, **kwargs):
        return b""


@pytest.fixture()
def controller(monkeypatch):
    _FakeClient.instances = []
    monkeypatch.setattr("app.ble.BleakClient", _FakeClient)
    ble = BleController()
    try:
        yield ble
    finally:
        ble.shutdown()


def _inspect(ble, address="AA:BB:CC:DD:EE:FF", name="SP630E"):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    results: list = []
    ble.inspection_finished.connect(results.append)
    ble.inspect_device(address, name)

    deadline = time.time() + 3
    while not results and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return results


def test_an_inspection_reports_what_the_device_offers(controller) -> None:
    results = _inspect(controller)

    assert len(results) == 1
    inspection = results[0]
    assert inspection.name == "SP630E"
    assert [service.uuid for service in inspection.services] == [
        "0000fff0-0000-1000-8000-00805f9b34fb"
    ]
    characteristics = inspection.services[0].characteristics
    assert [c.uuid for c in characteristics] == [
        "0000fff3-0000-1000-8000-00805f9b34fb",
        "0000fff4-0000-1000-8000-00805f9b34fb",
    ]
    assert characteristics[0].properties == ("write-without-response",)


def test_an_inspection_never_writes_to_the_device(controller) -> None:
    """The fake raises on any write; reaching the end means none was tried."""
    results = _inspect(controller)

    assert results and results[0].error == "", "the inspection failed, so it proves nothing"


def test_the_device_is_released_afterwards(controller) -> None:
    """Holding the link would keep the controller away from its own app, which
    is the very thing we ask the user to close."""
    _inspect(controller)

    assert _FakeClient.instances[-1].disconnected is True


def test_an_inspection_leaves_the_apps_own_connection_alone(controller) -> None:
    """It is not the connect path: no driver is chosen and nothing about the
    current strip changes."""
    before = (
        controller._client,
        controller._driver,
        controller._write_characteristic,
        controller._desired_power_on,
        controller._last_red,
    )

    _inspect(controller)

    assert (
        controller._client,
        controller._driver,
        controller._write_characteristic,
        controller._desired_power_on,
        controller._last_red,
    ) == before


def test_the_result_joins_the_diagnostic_snapshot(controller) -> None:
    _inspect(controller)

    snapshot = controller.scan_snapshot()
    assert len(snapshot.inspections) == 1
    assert snapshot.inspections[0].name == "SP630E"


def test_a_device_that_refuses_the_connection_is_reported_not_raised(controller, monkeypatch) -> None:
    class _Refusing(_FakeClient):
        async def connect(self):
            raise RuntimeError("device is busy")

    monkeypatch.setattr("app.ble.BleakClient", _Refusing)

    results = _inspect(controller)

    assert results and "busy" in results[0].error
    assert results[0].services == ()
    # Even a refused connection is released rather than left dangling.
    assert _FakeClient.instances[-1].disconnected is True

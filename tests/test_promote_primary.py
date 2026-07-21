"""Swapping which strip is the main one, and what happens to the old one.

Promoting used to silently keep the previous main strip connected as an extra,
so it kept lighting up with every shared command and users read that as "my
choice wasn't saved". The fate of the old primary is now an explicit choice,
applied inside one queued BLE operation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from app.ble import BleController
from app.ble_routing import swap_primary


class _Client:
    def __init__(self) -> None:
        self.is_connected = True
        self.disconnected = False

    async def disconnect(self) -> None:
        self.disconnected = True
        self.is_connected = False


def _conn(address: str, name: str = ""):
    return SimpleNamespace(
        address=address,
        client=_Client(),
        device=SimpleNamespace(address=address, name=name or address),
        driver=SimpleNamespace(id="bledom", display_name="BLEDOM"),
        write_characteristic=None,
        write_characteristics=[],
        preferred_payload_indices={},
        pacer=SimpleNamespace(reset=lambda: None),
    )


def _controller(primary, mirrors):
    """A BleController with its connection state filled in, no BLE stack."""
    controller = BleController.__new__(BleController)
    controller._client = primary.client
    controller._device = primary.device
    controller._driver = primary.driver
    controller._write_characteristic = None
    controller._write_characteristics = []
    controller._preferred_payload_indices = {}
    controller._pacer = primary.pacer
    controller._mirror_connections = list(mirrors)
    controller._reconnect_address = primary.address
    emitted: list[tuple] = []
    controller.mirrors_changed = SimpleNamespace(emit=lambda *a: emitted.append(("mirrors", *a)))
    controller.primary_changed = SimpleNamespace(emit=lambda *a: emitted.append(("primary", *a)))
    controller.status_changed = SimpleNamespace(emit=lambda *a: emitted.append(("status", *a)))
    return controller, emitted


def test_swap_keeps_the_old_primary_as_an_extra() -> None:
    old = _conn("AA:BB", "Old")
    new = _conn("CC:DD", "New")
    controller, emitted = _controller(old, [new])

    asyncio.run(controller._promote_mirror("CC:DD", keep_old_as_extra=True))

    assert controller._device.address == "CC:DD"
    assert controller._reconnect_address == "CC:DD"
    assert controller.mirror_addresses() == ["AA:BB"]  # old primary parked as extra
    assert old.client.disconnected is False
    status = [item for item in emitted if item[0] == "status"]
    assert status and "AA:BB" not in str(status[-1])  # message names it, not just the new one


def test_switch_disconnects_the_old_primary() -> None:
    old = _conn("AA:BB", "Old")
    new = _conn("CC:DD", "New")
    controller, _emitted = _controller(old, [new])

    asyncio.run(controller._promote_mirror("CC:DD", keep_old_as_extra=False))

    assert controller._device.address == "CC:DD"
    assert controller.mirror_addresses() == []  # nothing left to mirror
    assert old.client.disconnected is True


def test_switch_drops_only_the_old_primary() -> None:
    """Other extras keep following the new main strip."""
    old = _conn("AA:BB")
    new = _conn("CC:DD")
    other = _conn("EE:FF")
    controller, _ = _controller(old, [new, other])

    asyncio.run(controller._promote_mirror("CC:DD", keep_old_as_extra=False))

    assert controller.mirror_addresses() == ["EE:FF"]
    assert old.client.disconnected is True
    assert other.client.disconnected is False


def test_promoting_an_unknown_address_changes_nothing() -> None:
    old = _conn("AA:BB")
    new = _conn("CC:DD")
    controller, emitted = _controller(old, [new])

    asyncio.run(controller._promote_mirror("ZZ:ZZ", keep_old_as_extra=False))

    assert controller._device.address == "AA:BB"
    assert controller.mirror_addresses() == ["CC:DD"]
    assert old.client.disconnected is False
    assert emitted == []


def test_swap_primary_helper_parks_the_old_primary_last() -> None:
    from dataclasses import dataclass

    @dataclass
    class _S:
        address: str

    primary = _S("AA:BB")
    mirrors = [_S("CC:DD"), _S("EE:FF")]
    promoted, remaining = swap_primary(primary, mirrors, "EE:FF")
    assert promoted.address == "EE:FF"
    assert [m.address for m in remaining] == ["CC:DD", "AA:BB"]

"""Regression base for the controller drivers.

Adding support for a new controller must not quietly break the strips that
already work, and a driver must not advertise something it cannot actually emit.
These checks run over *every* registered driver, so a new one is covered the
moment it is added to the registry.
"""

from __future__ import annotations

import pytest

pytest.importorskip("bleak")

from app.ble_drivers import DRIVERS, get_driver_by_id
from app.driver_capabilities import capabilities_for

MAX_PAYLOAD_BYTES = 64
# Code 0 is the "static colour / no effect" sentinel: it is driven by the colour
# path, so a driver legitimately has no effect payload for it.
STATIC_COLOUR_CODE = 0


def _real_effect_codes(driver) -> list[int]:
    return [preset.code for preset in driver.effects if preset.code != STATIC_COLOUR_CODE]


def _payload_list(result) -> list[bytes]:
    if result is None:
        return []
    if isinstance(result, (bytes, bytearray)):
        return [bytes(result)]
    return [bytes(item) for item in result if item is not None]


def _assert_sane(payloads: list[bytes], what: str) -> None:
    assert payloads, f"{what}: expected at least one payload"
    for payload in payloads:
        assert isinstance(payload, bytes), f"{what}: payload must be bytes"
        assert 0 < len(payload) <= MAX_PAYLOAD_BYTES, f"{what}: implausible payload length {len(payload)}"


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.id)
def test_driver_identity_is_usable(driver) -> None:
    assert driver.id.strip()
    assert driver.display_name.strip()
    assert get_driver_by_id(driver.id) is driver


def test_driver_ids_are_unique() -> None:
    ids = [driver.id for driver in DRIVERS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.id)
def test_power_and_colour_always_produce_payloads(driver) -> None:
    _assert_sane(_payload_list(driver.power_payloads(True)), f"{driver.id} power on")
    _assert_sane(_payload_list(driver.power_payloads(False)), f"{driver.id} power off")
    for colour in ((0, 0, 0), (255, 255, 255), (10, 20, 30)):
        _assert_sane(_payload_list(driver.color_payloads(*colour)), f"{driver.id} colour {colour}")


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.id)
def test_brightness_payloads_are_well_formed_when_supported(driver) -> None:
    # A driver may legitimately have no brightness command (the app falls back to
    # scaling the colour); what it must not do is return malformed payloads.
    for value in (0, 50, 100):
        payloads = _payload_list(driver.brightness_payloads(value))
        for payload in payloads:
            assert isinstance(payload, bytes)
            assert 0 < len(payload) <= MAX_PAYLOAD_BYTES


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.id)
def test_every_advertised_effect_can_be_built(driver) -> None:
    # The effect list is what the UI offers the user — each entry must map to a
    # real payload, or the strip silently ignores an effect we showed.
    for code in _real_effect_codes(driver):
        payload = driver.effect_payload(code)
        assert payload is not None, f"{driver.id}: advertised effect {code} builds nothing"
        _assert_sane(_payload_list(payload), f"{driver.id} effect {code}")


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.id)
def test_speed_support_is_backed_by_a_real_command(driver) -> None:
    if not driver.supports_effect_speed():
        return
    codes = _real_effect_codes(driver)
    code = codes[0] if codes else 1
    emitted = _payload_list(driver.speed_payload(50)) or _payload_list(driver.effect_payload_with_speed(code, 50))
    assert emitted, f"{driver.id}: claims effect-speed support but emits no speed command"


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.id)
def test_payload_building_is_deterministic(driver) -> None:
    # Same request twice must give the same bytes; drivers keep per-connection
    # state, and a hidden dependency on it would make commands unrepeatable.
    assert _payload_list(driver.color_payloads(12, 34, 56)) == _payload_list(driver.color_payloads(12, 34, 56))
    assert _payload_list(driver.power_payloads(True)) == _payload_list(driver.power_payloads(True))


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.id)
def test_every_driver_has_declared_capabilities(driver) -> None:
    # Ties the 0.3.3 capability matrix to reality: a new driver without an entry
    # would silently fall back to the generic profile and lose its effects.
    caps = capabilities_for(driver.id)
    assert caps["rgb"] is True
    assert caps["firmware_effects"] is bool(driver.effects)

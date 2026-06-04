from __future__ import annotations

from app.ble_drivers.triones import (
    TRIONES_EFFECTS,
    TrionesDriver,
    build_effect_command,
    scale_speed_percent_to_triones_byte,
)


def test_triones_effect_payload_range() -> None:
    driver = TrionesDriver()

    assert driver.effect_payload(0x24) is None
    assert driver.effect_payload(0x25) == bytes.fromhex("bb 25 01 44")
    assert driver.effect_payload(0x38) == bytes.fromhex("bb 38 01 44")
    assert driver.effect_payload(0x39) is None


def test_triones_effect_command_clamps_only_helper_input() -> None:
    assert build_effect_command(0x25) == bytes.fromhex("bb 25 01 44")
    assert build_effect_command(0x38) == bytes.fromhex("bb 38 01 44")


def test_triones_effect_command_accepts_embedded_speed_byte() -> None:
    assert build_effect_command(0x25, 0x80) == bytes.fromhex("bb 25 80 44")
    assert build_effect_command(0x25, 0x00) == bytes.fromhex("bb 25 01 44")
    assert build_effect_command(0x25, 0x100) == bytes.fromhex("bb 25 ff 44")


def test_triones_effect_payload_with_speed_uses_embedded_speed_byte() -> None:
    driver = TrionesDriver()

    assert driver.supports_effect_speed() is True
    assert scale_speed_percent_to_triones_byte(100) == 0x01
    assert scale_speed_percent_to_triones_byte(0) == 0xFF
    assert driver.effect_payload_with_speed(0x25, 100) == bytes.fromhex("bb 25 01 44")
    assert driver.effect_payload_with_speed(0x25, 0) == bytes.fromhex("bb 25 ff 44")


def test_triones_declares_static_plus_supported_effects() -> None:
    codes = [effect.code for effect in TRIONES_EFFECTS]

    assert codes[0] == 0
    assert codes[1] == 0x25
    assert codes[-1] == 0x38
    assert len(codes) == 21


def test_triones_scales_color_by_remembered_brightness() -> None:
    driver = TrionesDriver()

    driver.remember_brightness(50)

    assert driver.color_payloads(100, 50, 10) == [bytes.fromhex("56 32 19 05 00 f0 aa")]


def test_triones_brightness_payload_uses_rgb_scaling_only() -> None:
    driver = TrionesDriver()

    assert driver.brightness_payloads(25) == []
    assert driver.color_payloads(200, 100, 40) == [bytes.fromhex("56 32 19 0a 00 f0 aa")]


def test_triones_reset_runtime_state_restores_full_color() -> None:
    driver = TrionesDriver()
    driver.remember_brightness(10)

    driver.reset_runtime_state()

    assert driver.color_payloads(100, 50, 10) == [bytes.fromhex("56 64 32 0a 00 f0 aa")]

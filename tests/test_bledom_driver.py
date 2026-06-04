from __future__ import annotations

from app.ble_drivers.bledom import BLEDOM_EFFECT_CODES, BledomDriver, build_effect_command
from app.quick_modes import QUICK_MODE_MAP


def test_bledom_effect_codes_use_safe_clone_range() -> None:
    assert min(BLEDOM_EFFECT_CODES) == 0x87
    assert max(BLEDOM_EFFECT_CODES) == 0x9C


def test_bledom_rejects_short_clone_ignored_effect_codes() -> None:
    driver = BledomDriver()

    for code in range(0x80, 0x87):
        assert driver.effect_payload(code) is None


def test_bledom_accepts_declared_effect_codes() -> None:
    driver = BledomDriver()

    assert driver.effect_payload(0x87) == bytes.fromhex("7e 00 03 87 03 00 00 00 ef")
    assert driver.effect_payload(0x9C) == bytes.fromhex("7e 00 03 9c 03 00 00 00 ef")


def test_bledom_does_not_clamp_unknown_effect_codes() -> None:
    driver = BledomDriver()

    assert driver.effect_payload(0x7F) is None
    assert driver.effect_payload(0x9D) is None
    assert build_effect_command(0x80) == bytes.fromhex("7e 00 03 80 03 00 00 00 ef")


def test_quick_rainbow_uses_supported_bledom_effect() -> None:
    driver = BledomDriver()
    rainbow_code = QUICK_MODE_MAP["rainbow"].effect_code

    assert driver.effect_payload(rainbow_code) is not None


def test_bledom_starts_with_primary_and_alt_payloads() -> None:
    driver = BledomDriver()

    assert driver.power_payloads(True) == [
        bytes.fromhex("7e 00 04 f0 00 01 ff 00 ef"),
        bytes.fromhex("cc 23 33"),
    ]


def test_bledom_remembers_primary_payload_variant() -> None:
    driver = BledomDriver()

    driver.remember_working_payload(bytes.fromhex("7e 00 04 f0 00 01 ff 00 ef"))

    assert driver.power_payloads(False) == [bytes.fromhex("7e 00 04 00 00 00 ff 00 ef")]
    assert driver.color_payloads(1, 2, 3) == [
        bytes.fromhex("7e 00 05 03 01 02 03 00 ef"),
        bytes.fromhex("56 01 02 03 00 f0 aa"),
    ]
    assert driver.brightness_payloads(50) == [
        bytes.fromhex("7e 00 01 32 00 00 00 00 ef"),
        bytes.fromhex("56 00 00 00 80 0f aa"),
    ]


def test_bledom_remembers_alt_payload_variant() -> None:
    driver = BledomDriver()

    driver.remember_working_payload(bytes.fromhex("cc 23 33"))

    assert driver.power_payloads(False) == [bytes.fromhex("cc 24 33")]
    assert driver.color_payloads(1, 2, 3) == [
        bytes.fromhex("7e 00 05 03 01 02 03 00 ef"),
        bytes.fromhex("56 01 02 03 00 f0 aa"),
    ]
    assert driver.brightness_payloads(50) == [
        bytes.fromhex("7e 00 01 32 00 00 00 00 ef"),
        bytes.fromhex("56 00 00 00 80 0f aa"),
    ]


def test_bledom_remembers_variants_per_command_family() -> None:
    driver = BledomDriver()

    driver.remember_working_payload(bytes.fromhex("7e 00 05 03 01 02 03 00 ef"))
    driver.remember_working_payload(bytes.fromhex("56 00 00 00 80 0f aa"))

    assert driver.color_payloads(4, 5, 6) == [bytes.fromhex("7e 00 05 03 04 05 06 00 ef")]
    assert driver.brightness_payloads(50) == [bytes.fromhex("56 00 00 00 80 0f aa")]


def test_bledom_brightness_starts_with_primary_payload() -> None:
    driver = BledomDriver()

    assert driver.brightness_payloads(100) == [
        bytes.fromhex("7e 00 01 64 00 00 00 00 ef"),
        bytes.fromhex("56 00 00 00 ff 0f aa"),
    ]


def test_bledom_reset_runtime_state_forgets_payload_variant() -> None:
    driver = BledomDriver()
    driver.remember_working_payload(bytes.fromhex("cc 23 33"))

    driver.reset_runtime_state()

    assert len(driver.power_payloads(True)) == 2

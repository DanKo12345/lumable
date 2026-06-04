from __future__ import annotations

from dataclasses import dataclass

from app.ble_drivers import detect_connected_driver, detect_scan_driver
from app.ble_drivers.magic_home import (
    MAGIC_HOME_EFFECTS,
    MAGIC_HOME_SERVICE_UUID,
    MAGIC_HOME_WRITE_UUID,
    MagicHomeDriver,
    build_color_command,
    build_effect_command,
    build_power_command,
)
from app.ble_drivers.triones import TrionesDriver


@dataclass
class FakeCharacteristic:
    uuid: str
    properties: list[str]


@dataclass
class FakeService:
    uuid: str
    characteristics: list[FakeCharacteristic]


def test_magic_home_payloads() -> None:
    assert build_power_command(True) == bytes.fromhex("cc 23 33")
    assert build_power_command(False) == bytes.fromhex("cc 24 33")
    assert build_color_command(300, -5, 42) == bytes.fromhex("56 ff 00 2a 00 f0 aa")


def test_magic_home_driver_is_explicitly_ble_not_wifi() -> None:
    driver = MagicHomeDriver()

    assert driver.display_name == "Magic Home BLE"
    assert driver.transport == "BLE"
    assert "Wi-Fi" in driver.protocol_notes
    assert driver.supports_effect_speed() is False


def test_magic_home_brightness_uses_rgb_scaling_only() -> None:
    driver = MagicHomeDriver()

    assert driver.brightness_payloads(25) == []
    assert driver.color_payloads(200, 100, 40) == [bytes.fromhex("56 32 19 0a 00 f0 aa")]


def test_magic_home_reset_runtime_state_restores_full_color() -> None:
    driver = MagicHomeDriver()
    driver.remember_brightness(10)

    driver.reset_runtime_state()

    assert driver.color_payloads(100, 50, 10) == [bytes.fromhex("56 64 32 0a 00 f0 aa")]


def test_magic_home_declares_static_plus_supported_effects() -> None:
    codes = [effect.code for effect in MAGIC_HOME_EFFECTS]

    assert codes[0] == 0
    assert codes[1] == 0x25
    assert codes[-1] == 0x38
    assert len(codes) == 21


def test_magic_home_effect_payload_range() -> None:
    driver = MagicHomeDriver()

    assert driver.effect_payload(0x24) is None
    assert driver.effect_payload(0x25) == bytes.fromhex("bb 00 01 25 44")
    assert driver.effect_payload(0x38) == bytes.fromhex("bb 00 01 38 44")
    assert driver.effect_payload(0x39) is None


def test_magic_home_effect_command_clamps_only_helper_input() -> None:
    assert build_effect_command(0x25) == bytes.fromhex("bb 00 01 25 44")
    assert build_effect_command(0x38) == bytes.fromhex("bb 00 01 38 44")


def test_magic_home_detects_scan_by_explicit_name() -> None:
    driver = detect_scan_driver("Magic Home", [MAGIC_HOME_SERVICE_UUID])

    assert isinstance(driver, MagicHomeDriver)


def test_magic_home_does_not_claim_conflicting_scan_uuid_without_name() -> None:
    driver = detect_scan_driver("Unknown", [MAGIC_HOME_SERVICE_UUID])

    assert driver is None


def test_magic_home_detects_connected_services_before_triones() -> None:
    services = [
        FakeService(
            MAGIC_HOME_SERVICE_UUID,
            [FakeCharacteristic(MAGIC_HOME_WRITE_UUID, ["write-without-response"])],
        )
    ]

    driver = detect_connected_driver("Magic Home", services)

    assert isinstance(driver, MagicHomeDriver)


def test_triones_name_wins_over_magic_home_uuid_conflict() -> None:
    services = [
        FakeService(
            MAGIC_HOME_SERVICE_UUID,
            [FakeCharacteristic(MAGIC_HOME_WRITE_UUID, ["write-without-response"])],
        )
    ]

    driver = detect_connected_driver("LEDBlue", services)

    assert isinstance(driver, TrionesDriver)


def test_magic_home_name_wins_over_triones_write_uuid_conflict() -> None:
    services = [
        FakeService(
            MAGIC_HOME_SERVICE_UUID,
            [FakeCharacteristic(MAGIC_HOME_WRITE_UUID, ["write-without-response"])],
        )
    ]

    driver = detect_connected_driver("Magic Home", services)

    assert isinstance(driver, MagicHomeDriver)


def test_triones_driver_rejects_magic_home_uuid_fallback_without_triones_name() -> None:
    services = [
        FakeService(
            MAGIC_HOME_SERVICE_UUID,
            [FakeCharacteristic(MAGIC_HOME_WRITE_UUID, ["write-without-response"])],
        )
    ]

    assert TrionesDriver().matches_services("Unknown", services) is False


def test_triones_explicit_name_still_wins_on_shared_magic_home_uuids() -> None:
    services = [
        FakeService(
            MAGIC_HOME_SERVICE_UUID,
            [FakeCharacteristic(MAGIC_HOME_WRITE_UUID, ["write-without-response"])],
        )
    ]

    assert TrionesDriver().matches_services("LEDBlue", services) is True


def test_triones_scan_name_is_not_claimed_by_magic_home_service_uuid() -> None:
    driver = detect_scan_driver("LED Blue", [MAGIC_HOME_SERVICE_UUID])

    assert isinstance(driver, TrionesDriver)


def test_magic_home_scan_name_is_not_claimed_by_triones() -> None:
    driver = detect_scan_driver("MagicLight", ["0000ffd0-0000-1000-8000-00805f9b34fb"])

    assert isinstance(driver, MagicHomeDriver)


def test_magic_home_prefers_ffe9_write_characteristic() -> None:
    driver = MagicHomeDriver()
    target = FakeCharacteristic(MAGIC_HOME_WRITE_UUID, ["write-without-response"])
    services = [
        FakeService(
            MAGIC_HOME_SERVICE_UUID,
            [
                FakeCharacteristic("00002a00-0000-1000-8000-00805f9b34fb", ["read"]),
                target,
            ],
        )
    ]

    assert driver.pick_write_characteristic(services) is target

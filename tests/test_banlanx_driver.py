from __future__ import annotations

from dataclasses import dataclass

from app.ble_drivers import detect_scan_driver
from app.ble_drivers.banlanx import (
    BANLANX_EFFECTS,
    BANLANX_SERVICE_UUID,
    BANLANX_WRITE_UUID,
    BanlanxDriver,
    build_v2_speed_command,
    scale_speed_percent_to_v2_byte,
)


@dataclass
class FakeCharacteristic:
    uuid: str
    properties: list[str]


@dataclass
class FakeService:
    uuid: str
    characteristics: list[FakeCharacteristic]


def test_banlanx_v3_names_without_e_use_v3_protocol() -> None:
    driver = BanlanxDriver()

    for name in ("SP613", "SP614", "SP623", "SP624"):
        driver.configure_for_device(name)

        assert driver.power_payloads(True) == [bytes.fromhex("0f 01 01")]


def test_banlanx_v2_names_without_e_stay_on_v2_protocol() -> None:
    driver = BanlanxDriver()

    for name in ("SP611", "SP617", "SP620", "SP621"):
        driver.configure_for_device(name)

        assert driver.power_payloads(True) == [bytes.fromhex("a0 62 01 01")]


def test_banlanx_scan_falls_back_to_service_uuid_when_name_is_missing() -> None:
    driver = detect_scan_driver("", ["0000ffe0-0000-1000-8000-00805f9b34fb"])

    assert isinstance(driver, BanlanxDriver)


def test_banlanx_connected_services_fall_back_to_uuids_when_name_is_missing() -> None:
    services = [
        FakeService(
            BANLANX_SERVICE_UUID,
            [FakeCharacteristic(BANLANX_WRITE_UUID, ["write-without-response"])],
        )
    ]

    assert BanlanxDriver().matches_services("", services) is True


def test_banlanx_declares_static_plus_supported_effects() -> None:
    codes = [effect.code for effect in BANLANX_EFFECTS]

    assert codes[0] == 0
    assert codes[1] == 0x01
    assert codes[-1] == 0x17
    assert len(codes) == 24


def test_banlanx_v2_effect_payload_range() -> None:
    driver = BanlanxDriver()
    driver.configure_for_device("SP611")

    assert driver.effect_payload(0x00) is None
    assert driver.effect_payload(0x01) == bytes.fromhex("a0 63 01 01")
    assert driver.effect_payload(0x17) == bytes.fromhex("a0 63 01 17")
    assert driver.effect_payload(0x18) is None


def test_banlanx_v2_speed_payload_uses_a0_67_command() -> None:
    driver = BanlanxDriver()
    driver.configure_for_device("SP611")

    assert driver.supports_effect_speed() is True
    assert scale_speed_percent_to_v2_byte(0) == 0x01
    assert scale_speed_percent_to_v2_byte(100) == 0x0A
    assert build_v2_speed_command(80) == bytes.fromhex("a0 67 01 08")
    assert driver.speed_payload(80) == bytes.fromhex("a0 67 01 08")


def test_banlanx_v3_effect_payload_range() -> None:
    driver = BanlanxDriver()
    driver.configure_for_device("SP613")

    assert driver.effect_payload(0x00) is None
    assert driver.effect_payload(0x01) == bytes.fromhex("14 01 01")
    assert driver.effect_payload(0x17) == bytes.fromhex("14 01 17")
    assert driver.effect_payload(0x18) is None


def test_banlanx_v3_does_not_claim_v2_speed_payload() -> None:
    driver = BanlanxDriver()
    driver.configure_for_device("SP613")

    assert driver.supports_effect_speed() is False
    assert driver.speed_payload(80) is None

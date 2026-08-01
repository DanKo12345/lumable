"""Naming a controller we cannot drive — and refusing to name one we cannot.

The whole point is that identification never turns into support: nothing here
may pick a driver or make a device connectable.
"""

from __future__ import annotations

from app.known_signatures import identify, identify_record
from app.scan_snapshot import AdvertisementRecord

SP630E = {0x5053: "1f10a1b2c3"}


def test_the_documented_sp630e_signature_is_recognised() -> None:
    known = identify(SP630E)

    assert known is not None
    assert known.display_name == "BanlanX SP630E"
    assert known.key == "banlanx_sp630e"


def test_another_company_with_the_same_bytes_is_not_it() -> None:
    """The payload only means something under BanlanX's company id."""
    assert identify({0x004C: "1f10a1b2c3"}) is None


def test_a_truncated_payload_reads_as_unidentified_not_a_crash() -> None:
    """Short advertisements are common; indexing one blindly would raise."""
    assert identify({0x5053: ""}) is None
    assert identify({0x5053: "1f"}) is None


def test_the_family_byte_has_to_agree_too() -> None:
    """The model byte alone would claim anything BanlanX ever numbered 0x1F."""
    assert identify({0x5053: "1f11a1b2"}) is None
    assert identify({0x5053: "2010a1b2"}) is None


def test_unreadable_hex_is_survived() -> None:
    assert identify({0x5053: "not hex at all"}) is None
    assert identify({0x5053: "1f1"}) is None  # odd length


def test_no_manufacturer_data_means_no_claim() -> None:
    assert identify(None) is None
    assert identify({}) is None


def test_a_name_alone_proves_nothing() -> None:
    """Anything can call itself SP630E, and the controller in the report that
    started this may advertise no name at all."""
    assert identify_record(AdvertisementRecord(name="SP630E")) is None
    assert identify_record(AdvertisementRecord(name="SP630E", service_uuids=("ffe0",))) is None


def test_a_record_carrying_the_signature_is_recognised() -> None:
    record = AdvertisementRecord(name="", manufacturer_data=SP630E)

    known = identify_record(record)

    assert known is not None
    assert known.display_name == "BanlanX SP630E"


def test_identifying_it_does_not_make_it_supported() -> None:
    """Recognition lives in the diagnostics layer. If we could drive it, it
    would have a driver and would never reach this module."""
    from app.ble_drivers import detect_scan_driver

    record = AdvertisementRecord(
        name="SP630E", manufacturer_data=SP630E, service_uuids=("ffe0",)
    )

    assert identify_record(record) is not None
    assert detect_scan_driver(record.name, list(record.service_uuids)) is None
    assert not hasattr(identify_record(record), "driver_id")


def test_the_card_names_it_without_offering_a_connection() -> None:
    """It gets its real name and still the check, never Connect: naming a
    controller is not the same as knowing how to command it."""
    from app.device_view_state import STATE_UNKNOWN, describe_device

    view = describe_device(
        selected={
            "name": "",
            "address": "AA:BB",
            "supported": False,
            "known_name": "BanlanX SP630E",
            "rssi": "-55",
        }
    )

    assert view.state == STATE_UNKNOWN
    assert view.detail == "BanlanX SP630E"
    assert view.title_key == "device.status.known_unsupported"
    assert view.action_key == "device.inspect"
    assert view.driver_name == "", "a recognised name must not become a claimed protocol"


def test_an_unrecognised_device_keeps_the_plainer_wording() -> None:
    from app.device_view_state import describe_device

    view = describe_device(selected={"name": "Mystery", "supported": False})

    assert view.title_key == "device.status.unknown_selected"
    assert view.detail == "Mystery"

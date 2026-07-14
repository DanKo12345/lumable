from __future__ import annotations

from app.device_names import (
    MAX_NAME_LEN,
    device_display_name,
    sanitize_device_name,
    validate_device_names,
)


def test_sanitize_trims_collapses_and_caps() -> None:
    assert sanitize_device_name("  Desk  ") == "Desk"
    assert sanitize_device_name("Living\n  Room") == "Living Room"
    assert sanitize_device_name(None) == ""
    assert len(sanitize_device_name("x" * 200)) == MAX_NAME_LEN


def test_validate_keeps_only_well_formed_pairs() -> None:
    out = validate_device_names(
        {
            "AA:BB": "  Desk ",
            "  ": "Nameless address",
            "CC:DD": "   ",  # blank name -> dropped
            "EE:FF": "TV",
        }
    )
    assert out == {"AA:BB": "Desk", "EE:FF": "TV"}


def test_validate_rejects_non_dict() -> None:
    assert validate_device_names(None) == {}
    assert validate_device_names(["AA:BB"]) == {}


def test_display_name_prefers_custom() -> None:
    names = {"AA:BB": "Shelf"}
    assert device_display_name("AA:BB", advertised="ELK-BLEDOM", names=names) == "Shelf"


def test_display_name_falls_back_to_advertised_then_address() -> None:
    assert device_display_name("AA:BB", advertised="ELK-BLEDOM", names={}) == "ELK-BLEDOM"
    assert device_display_name("AA:BB", advertised="", names={}) == "AA:BB"
    # Advertised equal to the address adds nothing -> show the address.
    assert device_display_name("AA:BB", advertised="AA:BB", names={}) == "AA:BB"

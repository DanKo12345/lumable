from __future__ import annotations

from app.driver_capabilities import CAPABILITY_FIELDS, capabilities_for, supports


def test_known_drivers_are_rgb_with_effects() -> None:
    for driver_id in ("bledom", "triones", "magic_home", "banlanx"):
        caps = capabilities_for(driver_id)
        assert caps["rgb"] is True
        assert caps["firmware_effects"] is True


def test_no_driver_claims_white_or_segments_yet() -> None:
    # Invariant: the current controllers are RGB-only. We must not pretend a
    # white channel (cct/rgbw) or addressable segments exist — that would let a
    # scene "apply" something the hardware can't show.
    for driver_id in ("bledom", "triones", "magic_home", "banlanx", "generic"):
        caps = capabilities_for(driver_id)
        assert caps["cct"] is False
        assert caps["rgbw"] is False
        assert caps["segments"] is False


def test_unknown_and_empty_fall_back_to_safe_rgb_only() -> None:
    for driver_id in (None, "", "made-up", "future-driver"):
        caps = capabilities_for(driver_id)
        assert caps["rgb"] is True
        assert caps["firmware_effects"] is False  # don't assume effects we can't drive
        assert caps["cct"] is False


def test_capabilities_are_case_insensitive_and_copied() -> None:
    assert capabilities_for("BLEDOM") == capabilities_for("bledom")
    caps = capabilities_for("bledom")
    caps["rgb"] = False  # mutating the result must not corrupt the table
    assert capabilities_for("bledom")["rgb"] is True


def test_every_entry_defines_all_fields() -> None:
    for driver_id in ("bledom", "triones", "magic_home", "banlanx", "generic", "unknown"):
        caps = capabilities_for(driver_id)
        assert set(caps) == set(CAPABILITY_FIELDS)


def test_supports_helper() -> None:
    assert supports("bledom", "rgb") is True
    assert supports("bledom", "cct") is False
    assert supports("nope", "firmware_effects") is False

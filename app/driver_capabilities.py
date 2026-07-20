"""What each controller driver can actually do — a small, Qt/bleak-free matrix.

Scene apply, the Local API and the UI all need to ask "does this strip support
X?" without touching the BLE layer. This module answers that from plain data
keyed by driver id, so it stays trivially testable and importable anywhere.

Design rules (0.3.3):
- **Conservative.** A capability is only ``True`` where the hardware genuinely
  supports it. The four controllers LumaBLE speaks today (BLEDOM, Triones, Magic
  Home, BanlanX) are plain RGB with built-in effects — none has a real white
  channel or addressable segments — so ``cct``/``rgbw``/``segments`` stay
  ``False``. We never emulate a white channel on an RGB-only strip.
- **effect *speed* is not here.** It is variant-dependent (e.g. BanlanX only on
  the v2 variant), so ask the live driver's ``supports_effect_speed()`` instead.
- Unknown ids fall back to a safe RGB-only profile.
"""

from __future__ import annotations

CAPABILITY_FIELDS = ("rgb", "rgbw", "cct", "firmware_effects", "segments")

_GENERIC: dict[str, bool] = {
    "rgb": True,
    "rgbw": False,
    "cct": False,
    "firmware_effects": False,
    "segments": False,
}

_RGB_WITH_EFFECTS: dict[str, bool] = {
    "rgb": True,
    "rgbw": False,
    "cct": False,
    "firmware_effects": True,
    "segments": False,
}

_MATRIX: dict[str, dict[str, bool]] = {
    "bledom": dict(_RGB_WITH_EFFECTS),
    "triones": dict(_RGB_WITH_EFFECTS),
    "magic_home": dict(_RGB_WITH_EFFECTS),
    "banlanx": dict(_RGB_WITH_EFFECTS),
    "generic": dict(_GENERIC),
}


def capabilities_for(driver_id: str | None) -> dict[str, bool]:
    """Static capabilities for a driver id. Unknown ids fall back to the safe
    RGB-only profile so nothing is assumed the hardware may not do."""
    return dict(_MATRIX.get(str(driver_id or "").strip().lower(), _GENERIC))


def supports(driver_id: str | None, field: str) -> bool:
    return bool(capabilities_for(driver_id).get(field, False))

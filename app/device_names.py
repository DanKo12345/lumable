"""User-assigned names for controllers, keyed by BLE address.

Multi-strip setups otherwise show identical-looking MAC addresses; a friendly
name ("Desk", "TV", "Shelf") makes the device list and mirror list readable.
Pure and storage-free so it's trivially testable.
"""

from __future__ import annotations

from typing import Any

MAX_NAME_LEN = 40


def sanitize_device_name(value: Any) -> str:
    """Trim, collapse internal whitespace, and cap the length of a name."""
    if value is None:
        return ""
    return " ".join(str(value).split())[:MAX_NAME_LEN]


def validate_device_names(data: Any) -> dict[str, str]:
    """Keep only well-formed ``address -> name`` pairs (both non-empty)."""
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, str] = {}
    for address, name in data.items():
        addr = str(address).strip()
        label = sanitize_device_name(name)
        if addr and label:
            cleaned[addr] = label
    return cleaned


def device_display_name(
    address: str,
    advertised: str = "",
    names: dict[str, str] | None = None,
) -> str:
    """Best label for a device: the user's custom name if set, else the
    advertised BLE name, else the raw address."""
    addr = str(address or "").strip()
    if names:
        custom = sanitize_device_name(names.get(addr, ""))
        if custom:
            return custom
    advertised_clean = str(advertised or "").strip()
    if advertised_clean and advertised_clean != addr:
        return advertised_clean
    return addr

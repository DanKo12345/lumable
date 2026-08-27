"""What a row of the discovery field stands for, and how to find it again.

The field used to hold one row per discovered controller, in the same order as
the list behind it, and the selected *position* was used to look the controller
up. That works exactly as long as the two stay identical — and they are about to
stop being identical, because the picker is growing group headings and a row
that collapses the unrecognised devices.

Nothing would have raised. A heading counted as a position, every controller
after it would shift by one, and pressing Connect would open a connection to a
different strip than the one highlighted. So a row now carries what it *is*,
rather than being identified by where it sits, and a controller is found by
address.

Pure: no Qt, no adapter, no window. The combo box is asked for the value it
holds; the deciding is done here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A row that stands for a controller somebody can connect to.
KIND_DEVICE = "device"
# A row that stands for anything else: "Scanning…", "Nothing found". Every kind
# below is distinguished by *kind* rather than by having no address, because a
# heading for a group could perfectly well want to carry one and must still
# never be connected to.
KIND_NOTICE = "notice"
# The name of a group, sitting above its members.
KIND_HEADING = "heading"
# "Other devices: 7" — opens the list of things no driver claims.
KIND_SHOW_UNKNOWN = "show_unknown"
# The way back out of that list.
KIND_BACK = "back"


@dataclass(frozen=True)
class ScanChoice:
    """The value behind one row of the discovery field."""

    kind: str
    address: str = ""


def device_choice(address: Any) -> ScanChoice:
    """A row standing for one controller."""
    return ScanChoice(kind=KIND_DEVICE, address=normalize_address(address))


def notice_choice() -> ScanChoice:
    """A row standing for anything that is not a controller."""
    return ScanChoice(kind=KIND_NOTICE)


def heading_choice() -> ScanChoice:
    """The name of a group of rows."""
    return ScanChoice(kind=KIND_HEADING)


def show_unknown_choice() -> ScanChoice:
    """The row that opens the devices no driver claims."""
    return ScanChoice(kind=KIND_SHOW_UNKNOWN)


def back_choice() -> ScanChoice:
    """The row that closes them again."""
    return ScanChoice(kind=KIND_BACK)


def kind_of(data: Any) -> str:
    """What a row is, for whoever has to act on being clicked.

    Anything unrecognised answers ``notice``: a row nobody has taught this
    module about is, by definition, not one to open a connection to.
    """
    return data.kind if isinstance(data, ScanChoice) else KIND_NOTICE


def normalize_address(value: Any) -> str:
    """One spelling of an address, so two sources can be compared.

    Upper case and stripped, matching how addresses are already stored for the
    extra strips. A comparison that works for the primary and fails for a
    mirror because one of them arrived lower case is the kind of fault that
    only shows up on somebody else's machine.
    """
    return str(value or "").strip().upper()


def address_of(data: Any) -> str:
    """The address a row stands for, or an empty string if it stands for none.

    Anything that is not a device row answers with an empty string, including
    the plain strings older code put here — a bare address is not proof that
    the row is a controller, only that somebody once stored one.
    """
    if isinstance(data, ScanChoice) and data.kind == KIND_DEVICE:
        return data.address
    return ""


def find_device(devices: Any, address: Any) -> dict | None:
    """The discovered device with this address, or ``None``.

    ``None`` is a real answer, not a failure: a row can name a controller that
    the newest scan no longer lists, and connecting to the device that happens
    to occupy that position instead is precisely what this module exists to
    prevent.
    """
    wanted = normalize_address(address)
    if not wanted:
        return None
    for device in devices or ():
        if isinstance(device, dict) and normalize_address(device.get("address")) == wanted:
            return device
    return None

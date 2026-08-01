"""Controllers we can name but cannot drive yet.

There is a middle ground between "supported" and "no idea what this is": a
device whose advertising signature is documented well enough to identify, while
its command protocol is not yet verified against real hardware. Telling the user
"BanlanX SP630E — recognised, control not supported yet" is far more useful than
"unknown device", and far more honest than pretending it works.

Nothing here selects a driver or permits a single BLE write. It is a label for
the diagnostics layer and the device card, and that is all.

The SP630E signature below comes from UniLED by monty68, MIT licensed:
https://github.com/monty68/uniled — see custom_components/uniled/lib/ble/
banlanx_6xx.py. Only the identifying constants are used; no implementation is
copied. Identifying a device is not the same as knowing how to command it, and
this module is deliberately the former only.
"""

from __future__ import annotations

from dataclasses import dataclass

# BanlanX assigns itself this company identifier in the advertisement.
_BANLANX_COMPANY_ID = 0x5053  # 20563

# First payload byte identifies the model, second the family. Both are checked:
# the model byte alone would claim anything BanlanX ever numbered 0x1F.
_SP630E_MODEL = 0x1F
_SP6XX_FAMILY = 0x10


@dataclass(frozen=True)
class KnownDevice:
    """A device we can name. ``supported`` is deliberately absent — if we could
    drive it, it would have a driver and would never reach this module."""

    key: str  # stable identifier for the signature
    display_name: str


_SP630E = KnownDevice(key="banlanx_sp630e", display_name="BanlanX SP630E")


def _payload_bytes(payload: str) -> bytes:
    """Hex string from a snapshot record back into bytes, tolerantly."""
    text = str(payload or "").strip()
    try:
        return bytes.fromhex(text)
    except ValueError:
        return b""


def identify(manufacturer_data: dict[int, str] | None) -> KnownDevice | None:
    """Name the device from its advertised manufacturer data, or None.

    The name in the advertisement is not evidence: anything can call itself
    SP630E, and the controller in the report that started this may not
    advertise a name at all. Only the signature counts.
    """
    if not manufacturer_data:
        return None
    payload = _payload_bytes(manufacturer_data.get(_BANLANX_COMPANY_ID, ""))
    # Length is checked before indexing: a truncated advertisement is common
    # enough, and it must read as "not identified" rather than raise.
    if len(payload) < 2:
        return None
    if payload[0] == _SP630E_MODEL and payload[1] == _SP6XX_FAMILY:
        return _SP630E
    return None


def identify_record(record) -> KnownDevice | None:
    """Same, for an :class:`~app.scan_snapshot.AdvertisementRecord`."""
    return identify(getattr(record, "manufacturer_data", None))

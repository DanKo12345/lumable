"""The order scan results are offered in, and which group each one belongs to.

Three groups, in one order that does not change: strips this person has chosen
before, then controllers a driver claims, then everything else that might be a
controller. Within a group the strongest signal leads.

The grouping outranks the signal on purpose. A neighbour's strip with a better
aerial is still a neighbour's strip, and putting it above the one on this desk
because it is momentarily louder is how a picker offers the wrong device to
somebody in a hurry.

Signal here means the median of everything a scan heard from that device, not
the last thing it happened to say. A device that was heard from too rarely to
be described in words is still ordered by what was heard: silence is thin
evidence, not a reason to bury it.

Pure. Trust is passed in rather than read from settings, and no ordering
decision consults anything outside the list being ordered — so the answer for
one scan cannot depend on a scan that came before it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.scan_choices import normalize_address
from app.signal_quality import SignalQuality, measure

GROUP_TRUSTED = "trusted"
GROUP_SUPPORTED = "supported"
GROUP_UNKNOWN = "unknown"

# The order the groups appear in, and the only place it is decided.
GROUP_ORDER = (GROUP_TRUSTED, GROUP_SUPPORTED, GROUP_UNKNOWN)


@dataclass(frozen=True)
class RankedDevice:
    """One scan result, with what was worked out about it alongside."""

    device: dict
    group: str
    quality: SignalQuality

    @property
    def address(self) -> str:
        return normalize_address(self.device.get("address"))


def group_of(device: Any, trusted: Any = ()) -> str:
    """Which group a result belongs in.

    Trust wins over recognition, and deliberately: a strip somebody has used
    for months belongs at the top of their list even on a day when its
    advertisement arrives too thin for a driver to be sure of it.
    """
    known = {normalize_address(item) for item in trusted or ()}
    known.discard("")
    if normalize_address(device.get("address")) in known:
        return GROUP_TRUSTED
    return GROUP_SUPPORTED if device.get("supported", True) else GROUP_UNKNOWN


def _sort_key(ranked: RankedDevice) -> tuple:
    median = ranked.quality.median
    return (
        GROUP_ORDER.index(ranked.group),
        # Nothing believable heard goes last within its group, rather than
        # counting as a reading of zero, which no radio reports and which would
        # put it at the very top.
        median is None,
        -(median if median is not None else 0.0),
        # Named before addressed: two identical strips differ only by address,
        # and the address is the part nobody reads. What this settles is that
        # they come out in the same order every time.
        str(ranked.device.get("name", "")).strip().lower(),
        ranked.address,
    )


def rank(devices: Any, *, trusted: Any = ()) -> list[RankedDevice]:
    """Every result, grouped and ordered, with its signal worked out once."""
    ranked = [
        RankedDevice(
            device=device,
            group=group_of(device, trusted),
            quality=measure(device.get("rssi_samples")),
        )
        for device in devices or ()
        if isinstance(device, dict)
    ]
    return sorted(ranked, key=_sort_key)


def by_signal(devices: Any) -> list[dict]:
    """The same ordering with no groups: strongest median first.

    For the places that have a single kind of thing to order and no knowledge
    of what this person trusts — deciding, for instance, which unrecognised
    devices are worth keeping when there are more than a list can show.
    """
    return [ranked.device for ranked in rank(devices)]

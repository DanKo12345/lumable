"""Everything one scan heard about each device, gathered as it arrives.

A five-second scan does not produce one description per device. It produces a
stream of advertisements, and the early ones are routinely incomplete: the first
callback for a device often carries no local name at all, because the name lives
in a scan response that has not been asked for yet. Whichever single event you
keep, you throw away something another event had.

So nothing is replaced here — it is merged. A name that has been heard is not
un-heard by a later event that lacks one, service UUIDs accumulate, and payloads
already seen are not overwritten by empty ones. Signal readings are the exception
and are all kept: one of them is a guess, and the point of scanning for five
seconds is to stop guessing.

Pure: given records, it decides. The object the library hands over for a later
connection is carried along untouched — the newest one, because it is the one
whose backing handle the library most recently refreshed — and nothing here
inspects its insides or scores it. Choosing between library objects by their
private fields would be a guess about a library, in a module whose whole purpose
is to stop guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.scan_snapshot import AdvertisementRecord, record_from_advertisement
from app.signal_quality import is_valid_reading

# What a reading is, is decided in one place and asked here. The bounds used to
# be restated in this module, with one copy accepting floats and the other only
# whole numbers — a difference that costs nothing until the day the two answer
# differently about the same value.


def _merge_payloads(kept: dict, arriving: dict) -> dict:
    """Add what is new; never let an empty payload erase one already seen."""
    merged = dict(kept)
    for key, payload in arriving.items():
        if payload or key not in merged:
            merged[key] = payload
    return merged


@dataclass
class ObservedDevice:
    """One device as a whole scan saw it, not as one event described it."""

    address: str = ""
    record: AdvertisementRecord = field(default_factory=AdvertisementRecord)
    rssi_samples: tuple[int, ...] = ()
    # The library's own object for this device, kept for the connection that may
    # follow. Opaque on purpose.
    handle: Any = None

    def merged_with(self, record: AdvertisementRecord, handle: Any) -> ObservedDevice:
        """This device, plus one more thing heard about it."""
        uuids = list(self.record.service_uuids)
        for uuid in record.service_uuids:
            if uuid not in uuids:
                uuids.append(uuid)
        samples = self.rssi_samples
        if is_valid_reading(record.rssi):
            # Kept whole: the library reports integers, and a reading stored as
            # a float would show up in a report as "-67.0".
            samples = (*samples, int(record.rssi))
        return ObservedDevice(
            address=self.address,
            record=AdvertisementRecord(
                # Last one that said anything. A device that renamed itself
                # mid-scan is far likelier than one that meant to go nameless.
                name=record.name.strip() or self.record.name,
                address=self.record.address or record.address,
                # The newest believable reading, so anything still reading a
                # single value sees the same field it always did.
                rssi=int(record.rssi) if is_valid_reading(record.rssi) else self.record.rssi,
                service_uuids=tuple(uuids),
                manufacturer_data=_merge_payloads(
                    self.record.manufacturer_data, record.manufacturer_data
                ),
                service_data=_merge_payloads(self.record.service_data, record.service_data),
                tx_power=record.tx_power if record.tx_power is not None else self.record.tx_power,
            ),
            rssi_samples=samples,
            handle=handle if handle is not None else self.handle,
        )


class ScanObservations:
    """What a scan has heard so far, by address.

    Fed from the scanner's callback and read once the scanner has stopped. It
    does no deciding beyond merging: which device is closest, and what to call
    that, is a separate question asked of the finished result.
    """

    def __init__(self) -> None:
        # Insertion ordered, and that order is kept: two devices that end up
        # equal on every measure should still come out in a repeatable order
        # rather than one that depends on how a dictionary happened to hash.
        self._devices: dict[str, ObservedDevice] = {}

    def observe(self, device: Any, advertisement: Any) -> None:
        """One advertisement, from the scanner's callback. Never raises.

        The callback runs on the event loop that is driving the scan; an
        exception here would stop the scan for the rest of its five seconds, and
        the device that caused it would be the one nobody could find.
        """
        try:
            record = record_from_advertisement(device, advertisement)
        except Exception:
            return
        address = str(record.address or "").strip().upper()
        if not address:
            return
        known = self._devices.get(address)
        if known is None:
            known = ObservedDevice(address=address)
        self._devices[address] = known.merged_with(record, device)

    def devices(self) -> list[ObservedDevice]:
        """Everything heard, in the order the devices were first heard."""
        return list(self._devices.values())

    def __len__(self) -> int:
        return len(self._devices)

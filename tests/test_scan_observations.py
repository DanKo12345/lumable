"""What a scan knows about a device, built from events that each know less.

The first advertisement for a device routinely arrives with no local name: the
name is in a scan response that has not come back yet. Later events can be
thinner still. Keeping any single one of them throws away what the others had,
and keeping the last one throws away the most — which is why the ordering of the
scripted callbacks below matters as much as their contents.
"""

from __future__ import annotations

from app.scan_observations import ScanObservations
from app.signal_quality import MAX_RSSI, MIN_RSSI, is_valid_reading


class _Device:
    """What the library hands over for a later connection."""

    def __init__(self, address: str, name: str | None = None, tag: str = "") -> None:
        self.address = address
        self.name = name
        self.tag = tag


class _Advertisement:
    def __init__(self, **kwargs) -> None:
        self.local_name = kwargs.get("local_name")
        self.rssi = kwargs.get("rssi", -60)
        self.service_uuids = kwargs.get("service_uuids", [])
        self.manufacturer_data = kwargs.get("manufacturer_data", {})
        self.service_data = kwargs.get("service_data", {})
        self.tx_power = kwargs.get("tx_power")


ADDRESS = "AA:BB:CC:DD:EE:01"


def _the_scripted_scan() -> ScanObservations:
    """Four events for one device, each carrying less than the whole truth.

    Deliberately in this order: the bare one first, because that is what really
    happens, and the empty one last, because that is the one that would erase
    everything if events replaced each other.
    """
    seen = ScanObservations()
    seen.observe(_Device(ADDRESS, tag="first"), _Advertisement(rssi=-70))
    seen.observe(
        _Device(ADDRESS, tag="second"), _Advertisement(rssi=-66, local_name="ELK-BLEDOM")
    )
    seen.observe(
        _Device(ADDRESS, tag="third"),
        _Advertisement(rssi=-72, service_uuids=["0000FFF0-0000-1000-8000-00805F9B34FB"]),
    )
    seen.observe(_Device(ADDRESS, tag="fourth"), _Advertisement(rssi=-68))
    return seen


def test_a_thin_event_does_not_undo_what_a_fuller_one_said() -> None:
    """The name arrived second and the UUID third; the fourth had neither. If
    events replaced each other the device would end the scan anonymous."""
    device = _the_scripted_scan().devices()[0]

    assert device.record.name == "ELK-BLEDOM"
    assert device.record.service_uuids == ("0000fff0-0000-1000-8000-00805f9b34fb",)
    assert device.rssi_samples == (-70, -66, -72, -68)


def test_every_reading_is_kept_not_the_last_one() -> None:
    """Four events, four readings. Keeping one is the guess this replaces —
    and −72 and −66 are six dB apart in the same five seconds."""
    device = _the_scripted_scan().devices()[0]

    assert len(device.rssi_samples) == 4
    assert min(device.rssi_samples) == -72
    assert max(device.rssi_samples) == -66


def test_the_newest_library_object_is_the_one_carried_forward() -> None:
    """Kept, not chosen. Scoring library objects by their internals would be
    guessing about a library, and the newest is the one it last refreshed."""
    device = _the_scripted_scan().devices()[0]

    assert device.handle.tag == "fourth"


def test_payloads_already_heard_are_not_wiped_by_empty_ones() -> None:
    """Manufacturer data is the single most telling field for working out which
    family a controller belongs to. An event that simply lacks it is not a
    device announcing that it has none."""
    seen = ScanObservations()
    seen.observe(
        _Device(ADDRESS),
        _Advertisement(manufacturer_data={0x5254: b"\x01\x02"}, service_data={"fff0": b"\x09"}),
    )
    seen.observe(_Device(ADDRESS), _Advertisement())
    device = seen.devices()[0]

    assert device.record.manufacturer_data == {0x5254: "0102"}
    assert device.record.service_data == {"fff0": "09"}


def test_a_company_that_says_nothing_does_not_unsay_what_it_said() -> None:
    """The sharper case, and the one the guard is really for.

    An event carrying no manufacturer data at all cannot erase anything — there
    is no key to overwrite. An event carrying the same company id with an empty
    payload can, and that is what a device does when the interesting part rode
    in a scan response the second event did not include.
    """
    seen = ScanObservations()
    seen.observe(_Device(ADDRESS), _Advertisement(manufacturer_data={0x5254: b"\x01\x02"}))
    seen.observe(_Device(ADDRESS), _Advertisement(manufacturer_data={0x5254: b""}))
    device = seen.devices()[0]

    assert device.record.manufacturer_data == {0x5254: "0102"}, (
        "an empty payload replaced the one that identified the controller"
    )


def test_a_later_event_may_still_add_a_new_payload() -> None:
    """Not frozen either: what is refused is erasure, not news."""
    seen = ScanObservations()
    seen.observe(_Device(ADDRESS), _Advertisement(manufacturer_data={0x5254: b"\x01"}))
    seen.observe(_Device(ADDRESS), _Advertisement(manufacturer_data={0x004C: b"\x02"}))
    device = seen.devices()[0]

    assert device.record.manufacturer_data == {0x5254: "01", 0x004C: "02"}


def test_readings_outside_what_a_radio_can_report_are_not_counted() -> None:
    """A library filling a gap, or a driver reporting an error as a number.

    The rule itself is asserted where it lives; what this checks is that the
    accumulator asks it rather than keeping its own idea of the bounds.
    """
    assert is_valid_reading(MIN_RSSI) and is_valid_reading(MAX_RSSI)
    assert not is_valid_reading(MIN_RSSI - 1)
    assert not is_valid_reading(MAX_RSSI + 1)
    assert not is_valid_reading(None)
    assert not is_valid_reading("-60")
    # True is an int in Python, and would otherwise count as a reading of 1.
    assert not is_valid_reading(True)

    seen = ScanObservations()
    seen.observe(_Device(ADDRESS), _Advertisement(rssi=-64))
    seen.observe(_Device(ADDRESS), _Advertisement(rssi=127))
    seen.observe(_Device(ADDRESS), _Advertisement(rssi=None))
    device = seen.devices()[0]

    assert device.rssi_samples == (-64,)
    assert device.record.rssi == -64, "an impossible reading became the device's signal"


def test_devices_come_back_in_the_order_they_were_first_heard() -> None:
    """Two devices that end up equal on every measure should still come out in
    a repeatable order, rather than one that depends on hashing."""
    seen = ScanObservations()
    seen.observe(_Device("AA:BB:CC:DD:EE:01"), _Advertisement(rssi=-60))
    seen.observe(_Device("AA:BB:CC:DD:EE:02"), _Advertisement(rssi=-60))
    seen.observe(_Device("AA:BB:CC:DD:EE:01"), _Advertisement(rssi=-61))

    assert [device.address for device in seen.devices()] == [
        "AA:BB:CC:DD:EE:01",
        "AA:BB:CC:DD:EE:02",
    ]


def test_the_same_strip_spelled_two_ways_is_one_device() -> None:
    """Addresses arrive from more than one place and not always in one case."""
    seen = ScanObservations()
    seen.observe(_Device("aa:bb:cc:dd:ee:01"), _Advertisement(rssi=-60))
    seen.observe(_Device("AA:BB:CC:DD:EE:01"), _Advertisement(rssi=-62))

    assert len(seen) == 1
    assert seen.devices()[0].rssi_samples == (-60, -62)


def test_an_event_that_cannot_be_read_costs_a_reading_not_the_scan() -> None:
    """The callback runs on the loop driving the scan. An exception there stops
    the scan for the rest of its five seconds, and the device that caused it is
    the one nobody can find."""

    class _Hostile:
        @property
        def address(self):
            raise RuntimeError("no address today")

    seen = ScanObservations()
    seen.observe(_Hostile(), _Advertisement(rssi=-60))
    seen.observe(_Device(ADDRESS), _Advertisement(rssi=-61))

    assert [device.address for device in seen.devices()] == [ADDRESS]


def test_an_event_with_no_address_is_not_a_device() -> None:
    """There is nothing to connect to and nothing to merge it into later."""
    seen = ScanObservations()
    seen.observe(_Device(""), _Advertisement(rssi=-60))

    assert seen.devices() == []

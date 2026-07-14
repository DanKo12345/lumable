"""Safe protocol auto-detection for unrecognised BLE LED controllers.

When no driver claims a device, we still want to *suggest* one to try. This
module scores each known driver against the device's GATT profile — the service
and characteristic UUIDs it advertises, whether they're writable, and the
advertised name. It NEVER sends a command, so the strip can't blink or change
while we probe: it's pure inspection of what the device already exposes.

Kept free of bleak/Qt so the scoring is trivially testable; a thin wrapper in
``app.ble_drivers`` adapts live bleak services into these plain structures.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# Score weights for the signals we can read without touching the device.
_NAME_MATCH = 40
_WRITABLE_KNOWN_CHAR = 50
_KNOWN_CHAR_NOT_WRITABLE = 15
_SERVICE_MATCH = 25

# A candidate is only worth offering to the user if it clears this — i.e. it has
# some real signal (a matching service, name, or known characteristic), not just
# "this device happens to have a writable characteristic".
OFFER_THRESHOLD = 25


@dataclass(frozen=True)
class DriverProfile:
    """The identifying markers of one driver, lifted off the driver class."""

    id: str
    display_name: str
    name_tokens: tuple[str, ...] = ()
    scan_service_uuids: frozenset[str] = frozenset()
    interesting_service_uuids: frozenset[str] = frozenset()
    known_write_uuids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DeviceProfile:
    """What an unknown device advertises, normalised to lowercase UUID sets."""

    name: str = ""
    service_uuids: frozenset[str] = frozenset()
    char_uuids: frozenset[str] = frozenset()
    writable_char_uuids: frozenset[str] = frozenset()


@dataclass
class ProbeCandidate:
    driver_id: str
    display_name: str
    score: int
    reasons: list[str] = field(default_factory=list)


def score_driver(driver: DriverProfile, device: DeviceProfile) -> ProbeCandidate:
    """Score one driver against a device from inspection alone (no writes)."""
    reasons: list[str] = []
    # Without a writable characteristic there's nothing to send commands to, so
    # the driver can't possibly control this device — score it out.
    if not device.writable_char_uuids:
        return ProbeCandidate(driver.id, driver.display_name, 0, ["no writable characteristic"])

    score = 0
    lowered = device.name.lower()
    if any(token and token in lowered for token in driver.name_tokens):
        score += _NAME_MATCH
        reasons.append("name matches")

    known = driver.known_write_uuids & device.char_uuids
    if known & device.writable_char_uuids:
        score += _WRITABLE_KNOWN_CHAR
        reasons.append("writable known characteristic")
    elif known:
        score += _KNOWN_CHAR_NOT_WRITABLE
        reasons.append("known characteristic present")

    services = (driver.scan_service_uuids | driver.interesting_service_uuids) & device.service_uuids
    if services:
        score += _SERVICE_MATCH
        reasons.append("service UUID matches")

    return ProbeCandidate(driver.id, driver.display_name, score, reasons)


def rank_candidates(
    drivers: Iterable[DriverProfile],
    device: DeviceProfile,
    *,
    min_score: int = 1,
) -> list[ProbeCandidate]:
    """Ranked driver candidates for a device, best first, ties broken by name."""
    scored = [score_driver(driver, device) for driver in drivers]
    viable = [candidate for candidate in scored if candidate.score >= min_score]
    viable.sort(key=lambda candidate: (-candidate.score, candidate.display_name))
    return viable


def best_offer(
    drivers: Iterable[DriverProfile],
    device: DeviceProfile,
) -> ProbeCandidate | None:
    """The single candidate worth offering to try, or None if nothing is a
    confident-enough guess to suggest."""
    ranked = rank_candidates(drivers, device, min_score=OFFER_THRESHOLD)
    return ranked[0] if ranked else None

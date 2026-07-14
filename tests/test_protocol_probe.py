from __future__ import annotations

from app.protocol_probe import (
    OFFER_THRESHOLD,
    DeviceProfile,
    DriverProfile,
    best_offer,
    rank_candidates,
    score_driver,
)

BLEDOM = DriverProfile(
    id="bledom",
    display_name="BLEDOM",
    name_tokens=("bledom", "elk-bledom"),
    scan_service_uuids=frozenset({"0000fff0-0000-1000-8000-00805f9b34fb"}),
    known_write_uuids=frozenset({"0000fff3-0000-1000-8000-00805f9b34fb"}),
)
TRIONES = DriverProfile(
    id="triones",
    display_name="Triones",
    name_tokens=("triones",),
    scan_service_uuids=frozenset({"0000ffd5-0000-1000-8000-00805f9b34fb"}),
    known_write_uuids=frozenset({"0000ffd9-0000-1000-8000-00805f9b34fb"}),
)
DRIVERS = [BLEDOM, TRIONES]


def _device(*, name="", services=(), chars=(), writable=()) -> DeviceProfile:
    return DeviceProfile(
        name=name,
        service_uuids=frozenset(services),
        char_uuids=frozenset(chars),
        writable_char_uuids=frozenset(writable),
    )


def test_writable_known_characteristic_scores_highest() -> None:
    write = "0000fff3-0000-1000-8000-00805f9b34fb"
    device = _device(
        name="Unknown Gadget",
        services=("0000fff0-0000-1000-8000-00805f9b34fb",),
        chars=(write,),
        writable=(write,),
    )
    candidate = score_driver(BLEDOM, device)
    # Known writable characteristic + matching service.
    assert candidate.score >= 50
    assert "writable known characteristic" in candidate.reasons


def test_name_match_contributes() -> None:
    write = "0000abcd-0000-1000-8000-00805f9b34fb"
    device = _device(name="ELK-BLEDOM-1234", chars=(write,), writable=(write,))
    candidate = score_driver(BLEDOM, device)
    assert "name matches" in candidate.reasons
    assert candidate.score >= 40


def test_no_writable_characteristic_scores_zero() -> None:
    # Advertises the service but nothing is writable -> can't be driven.
    device = _device(services=("0000fff0-0000-1000-8000-00805f9b34fb",))
    assert score_driver(BLEDOM, device).score == 0


def test_ranking_orders_best_first() -> None:
    bledom_write = "0000fff3-0000-1000-8000-00805f9b34fb"
    device = _device(
        name="bledom strip",
        services=("0000fff0-0000-1000-8000-00805f9b34fb",),
        chars=(bledom_write,),
        writable=(bledom_write,),
    )
    ranked = rank_candidates(DRIVERS, device)
    assert ranked[0].driver_id == "bledom"


def test_best_offer_returns_none_without_signal() -> None:
    # A writable characteristic exists, but nothing matches any driver's markers.
    write = "0000dead-0000-1000-8000-00805f9b34fb"
    device = _device(name="Generic Light", chars=(write,), writable=(write,))
    assert best_offer(DRIVERS, device) is None


def test_best_offer_returns_confident_candidate() -> None:
    write = "0000ffd9-0000-1000-8000-00805f9b34fb"
    device = _device(
        name="HappyLight",
        services=("0000ffd5-0000-1000-8000-00805f9b34fb",),
        chars=(write,),
        writable=(write,),
    )
    offer = best_offer(DRIVERS, device)
    assert offer is not None
    assert offer.driver_id == "triones"
    assert offer.score >= OFFER_THRESHOLD

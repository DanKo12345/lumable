"""The device card's five states, decided in one place.

Every assertion is about what the user is told, because the point of folding
this into one function is that the card cannot say two things at once.
"""

from __future__ import annotations

from app.device_view_state import (
    STATE_CHECKING,
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_ERROR,
    STATE_IDLE,
    STATE_SCANNING,
    STATE_SUPPORTED,
    STATE_UNKNOWN,
    describe_device,
)


def _supported(name="ELK-BLEDOM", driver="BLEDOM", rssi="-48"):
    return {"name": name, "driver": driver, "rssi": rssi, "supported": True}


def _unknown(name="SP630E", rssi="-55"):
    return {"name": name, "rssi": rssi, "supported": False}


def test_nothing_found_yet_says_so_and_offers_nothing() -> None:
    view = describe_device()

    assert view.state == STATE_IDLE
    assert view.action_enabled is False


def test_a_supported_strip_names_its_driver_and_offers_connecting() -> None:
    view = describe_device(selected=_supported())

    assert view.state == STATE_SUPPORTED
    assert view.detail == "ELK-BLEDOM"
    assert view.driver_name == "BLEDOM"
    assert view.signal_rssi == -48
    assert view.action_key == "device.connect"
    assert view.action_enabled is True


def test_an_unrecognised_device_offers_a_check_and_claims_no_driver() -> None:
    """Naming a driver here would be a guess, and the guess is the thing this
    whole path exists to avoid."""
    view = describe_device(selected=_unknown())

    assert view.state == STATE_UNKNOWN
    assert view.is_unknown is True
    assert view.driver_name == ""
    assert view.action_key == "device.inspect"


def test_a_running_check_outranks_the_selection_behind_it() -> None:
    view = describe_device(checking=True, selected=_unknown())

    assert view.state == STATE_CHECKING
    assert view.is_busy is True
    assert view.action_enabled is False, "the check must not be startable twice"


def test_connecting_outranks_a_found_device() -> None:
    view = describe_device(connecting=True, selected=_supported())

    assert view.state == STATE_CONNECTING
    assert view.action_enabled is False


def test_being_connected_outranks_everything_else() -> None:
    view = describe_device(
        connected=True, scanning=True, connecting=True, checking=True, connected_name="Desk"
    )

    assert view.state == STATE_CONNECTED
    assert view.detail == "Desk"
    assert view.action_key == "device.disconnect"


def test_scanning_is_shown_while_it_runs() -> None:
    view = describe_device(scanning=True)

    assert view.state == STATE_SCANNING
    assert view.is_busy is True


def test_a_problem_outranks_a_stale_success() -> None:
    """The card must not keep showing a found device while the last attempt
    failed — the user would try the same thing again."""
    view = describe_device(error="The strip stopped responding.", selected=_supported())

    assert view.state == STATE_ERROR
    assert view.detail == "The strip stopped responding."


def test_a_connected_controller_lists_only_what_it_reports() -> None:
    view = describe_device(
        connected=True,
        connected_name="Desk",
        driver_name="BLEDOM",
        capabilities={"power": True, "color": True, "brightness": False, "effects": 22},
    )

    assert view.facts == (
        ("device.fact.power", "device.fact.yes"),
        ("device.fact.color", "device.fact.yes"),
        ("device.fact.brightness", "device.fact.no"),
        ("device.fact.effects", "22"),
    )


def test_a_controller_that_reports_nothing_shows_no_list_of_dashes() -> None:
    assert describe_device(connected=True, connected_name="Desk").facts == ()
    assert describe_device(connected=True, capabilities={}).facts == ()


def test_an_unreadable_signal_is_absent_rather_than_zero() -> None:
    """Zero would read as a very strong signal."""
    view = describe_device(selected={"name": "x", "rssi": "-", "supported": True})

    assert view.signal_rssi is None

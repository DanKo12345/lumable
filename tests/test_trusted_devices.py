"""Which strips this person actually chose, as opposed to which one answered.

``last_device_address`` records whatever was connected last, and the app
connects on its own to a single supported controller it finds. So if your strip
is switched off while a neighbour's is not, the address that gets remembered is
theirs — which is exactly why "the strip we last connected to" cannot be the
same thing as "a strip this person trusts".

The list is filled once from what is already set up, so nobody upgrading is
asked to re-approve strips they have been using for months. After that it is
only ever added to deliberately. The distinction that carries all of this is
between a key that is absent and a key that is empty: absent means nobody has
been asked yet, empty means somebody answered.
"""

from __future__ import annotations

from app.storage import validate_settings


def _trusted(**settings) -> list[str]:
    return validate_settings(settings)["trusted_device_addresses"]


def test_an_existing_setup_is_taken_at_its_word_once() -> None:
    """Nobody upgrading should have to re-approve the strips they already use."""
    trusted = _trusted(
        last_device_address="AA:BB:CC:DD:EE:01",
        extra_device_addresses=["AA:BB:CC:DD:EE:02"],
    )

    assert trusted == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]


def test_an_empty_list_is_an_answer_and_is_left_alone() -> None:
    """The one thing this list exists not to do. Refilling it from the last
    connection would undo the removal on the very next load, and the address it
    refilled from is the one that might not be theirs at all."""
    trusted = _trusted(
        trusted_device_addresses=[],
        last_device_address="AA:BB:CC:DD:EE:01",
        extra_device_addresses=["AA:BB:CC:DD:EE:02"],
    )

    assert trusted == []


def test_a_list_that_exists_is_not_topped_up_from_the_last_connection() -> None:
    """Not only when empty: a person who trusts one strip and connected to
    another has not thereby trusted the second."""
    trusted = _trusted(
        trusted_device_addresses=["AA:BB:CC:DD:EE:09"],
        last_device_address="AA:BB:CC:DD:EE:01",
        extra_device_addresses=["AA:BB:CC:DD:EE:02"],
    )

    assert trusted == ["AA:BB:CC:DD:EE:09"]


def test_validating_the_result_again_changes_nothing() -> None:
    """Settings are loaded, saved and loaded again constantly. A migration that
    was not idempotent would show up as a list that grows a little every time
    the app starts."""
    first = validate_settings(
        {
            "last_device_address": "AA:BB:CC:DD:EE:01",
            "extra_device_addresses": ["AA:BB:CC:DD:EE:02"],
        }
    )
    second = validate_settings(first)
    third = validate_settings(second)

    assert first["trusted_device_addresses"] == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]
    assert second["trusted_device_addresses"] == first["trusted_device_addresses"]
    assert third["trusted_device_addresses"] == first["trusted_device_addresses"]


def test_the_same_strip_written_two_ways_is_listed_once() -> None:
    """Addresses reach the file from more than one place and not always in one
    case. Two spellings of one strip would show up as two rows in the picker."""
    trusted = _trusted(
        last_device_address="aa:bb:cc:dd:ee:01",
        extra_device_addresses=["AA:BB:CC:DD:EE:01", " AA:BB:CC:DD:EE:02 "],
    )

    assert trusted == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]


def test_a_setup_with_no_strip_yet_trusts_nothing() -> None:
    """A first run has an empty primary, and an empty string is not an address
    anybody could connect to."""
    assert _trusted(last_device_address="", extra_device_addresses=[]) == []
    assert _trusted() == []


def test_only_extras_still_migrate() -> None:
    """The primary can be empty while extras are not — a strip removed as the
    main one but kept as a mirror."""
    trusted = _trusted(
        last_device_address="",
        extra_device_addresses=["AA:BB:CC:DD:EE:02"],
    )

    assert trusted == ["AA:BB:CC:DD:EE:02"]


def test_rubbish_in_the_stored_list_is_dropped_rather_than_kept() -> None:
    """A hand-edited or half-written file must not put ``None`` where an
    address goes; the next thing that happens to it is a connection attempt."""
    trusted = _trusted(
        trusted_device_addresses=["AA:BB:CC:DD:EE:01", None, 42, "", "AA:BB:CC:DD:EE:01"],
    )

    assert trusted == ["AA:BB:CC:DD:EE:01"]

"""What a scan is entitled to say about a device's signal.

Two claims are made here and they are separate on purpose: how strong the signal
is, and how sure we are. Conflating them produces the specific untruth this
module exists to avoid — a strip on the desk that advertises rarely being called
weak, when what is thin is the evidence and not the radio.

The other property under test is independence. A device's word depends on its
own readings and on nothing that any other device did, because a label that
moves when a neighbour appears is a ranking pretending to be a measurement.
"""

from __future__ import annotations

import math

import pytest

from app.signal_quality import (
    LEVEL_INSUFFICIENT,
    LEVEL_MEDIUM,
    LEVEL_STRONG,
    LEVEL_WEAK,
    MIN_SAMPLES_FOR_A_LEVEL,
    STRONG_FROM_DBM,
    WEAK_BELOW_DBM,
    measure,
    median_of,
    valid_readings,
)


# ── the boundaries, exactly ───────────────────────────────────────────
def test_the_strong_boundary_is_included() -> None:
    """Written as "median >= −60" and tested at −60, because an off-by-one here
    is invisible in any ordinary sample and permanent once shipped."""
    assert measure([STRONG_FROM_DBM] * 3).level == LEVEL_STRONG
    assert measure([STRONG_FROM_DBM - 1] * 3).level == LEVEL_MEDIUM


def test_the_weak_boundary_is_included_in_the_middle_band() -> None:
    """−80 is still medium; below it is weak."""
    assert measure([WEAK_BELOW_DBM] * 3).level == LEVEL_MEDIUM
    assert measure([WEAK_BELOW_DBM - 1] * 3).level == LEVEL_WEAK


# ── how sure, as its own question ─────────────────────────────────────
@pytest.mark.parametrize("count", [0, 1, 2])
def test_too_few_readings_is_not_a_verdict_about_the_radio(count: int) -> None:
    """A strip on the desk may advertise rarely. Calling that a weak signal is
    a statement about hardware made from a shortage of evidence."""
    quality = measure([-40] * count)

    assert quality.level == LEVEL_INSUFFICIENT
    assert quality.samples == count
    assert quality.is_confident is False


def test_the_third_reading_is_what_earns_a_word() -> None:
    assert MIN_SAMPLES_FOR_A_LEVEL == 3
    assert measure([-40, -41]).level == LEVEL_INSUFFICIENT
    assert measure([-40, -41, -42]).level == LEVEL_STRONG


def test_a_median_is_still_reported_when_there_is_no_confident_word() -> None:
    """It orders the list and it goes into the report. Withholding it would
    drop a device to the bottom for having been quiet, which is the opposite of
    what thin evidence means."""
    quality = measure([-55, -57])

    assert quality.level == LEVEL_INSUFFICIENT
    assert quality.median == -56.0


def test_nothing_believable_leaves_no_median_at_all() -> None:
    """Distinct from a median of zero, which is a reading no radio reports."""
    assert measure([]).median is None
    assert measure(None).median is None
    assert measure(["-60", None, float("nan")]).median is None


# ── the median itself ─────────────────────────────────────────────────
def test_an_even_number_of_readings_gives_the_midpoint() -> None:
    assert median_of([-70.0, -60.0]) == -65.0
    assert median_of([-71.0, -70.0, -60.0, -59.0]) == -65.0


def test_a_fractional_median_is_not_rounded_away() -> None:
    """It is compared against the thresholds and shown in a report; rounding it
    here would move a device across a boundary for the sake of tidiness."""
    assert median_of([-61.0, -60.0]) == -60.5
    assert measure([-61, -60, -61, -60]).median == -60.5
    assert measure([-61, -60, -61, -60]).level == LEVEL_MEDIUM


def test_one_lucky_packet_does_not_carry_the_verdict() -> None:
    """The whole reason for taking a median. A distant strip that gets one
    strong reading in five seconds used to outrank a close one that did not.
    """
    steady_and_far = [-85, -86, -84, -87, -85]
    with_one_fluke = [*steady_and_far, -35]

    assert measure(steady_and_far).level == LEVEL_WEAK
    assert measure(with_one_fluke).level == LEVEL_WEAK
    assert measure(with_one_fluke).median <= -84.0


def test_the_order_the_readings_arrived_in_changes_nothing() -> None:
    readings = [-72, -55, -90, -61, -68]

    first = measure(readings)
    shuffled = measure(list(reversed(readings)))

    assert (first.median, first.level, first.samples) == (
        shuffled.median,
        shuffled.level,
        shuffled.samples,
    )


# ── what counts as a reading ──────────────────────────────────────────
def test_impossible_values_are_refused_by_this_function_too() -> None:
    """Filtered again even though the accumulator filters. An answer that is
    only right because of what another module did earlier is right by
    arrangement, and the arrangement is the first thing to go."""
    assert valid_readings([-128, 21, "-60", None, [], float("inf"), -math.inf]) == []
    assert valid_readings([-127, 20]) == [-127.0, 20.0]


def test_a_true_is_not_a_reading_of_one() -> None:
    """``bool`` is an ``int`` in Python. Counted, it sits inside the valid range
    and drags a median up by a hundred dB."""
    assert valid_readings([True, False]) == []
    assert measure([-90, -90, -90, True]).level == LEVEL_WEAK


def test_rubbish_does_not_buy_confidence() -> None:
    """Two real readings and three impossible ones is still two readings. The
    count that decides is the count of what survived."""
    quality = measure([-50, "-50", None, float("nan"), -52])

    assert quality.samples == 2
    assert quality.level == LEVEL_INSUFFICIENT


# ── independence from everything else in the scan ─────────────────────
def test_a_device_is_judged_alone() -> None:
    """A neighbour with a better aerial cannot re-label the strip in front of
    you. Nothing is passed in but one device's readings, and this is the test
    that would fail the day somebody adds a "scan context" argument."""
    mine = [-63, -64, -62]
    alone = measure(mine)

    for neighbour in ([-20, -21, -19], [-110, -111, -109], []):
        # The neighbour is measured too, in the same run, to make the point that
        # nothing accumulates between calls.
        measure(neighbour)
        assert measure(mine) == alone


def test_two_devices_with_the_same_readings_get_the_same_answer() -> None:
    assert measure([-70, -71, -69]) == measure([-69, -70, -71])

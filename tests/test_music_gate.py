"""The noise gate in decibels: one mapping, and a threshold that survives the move."""

from __future__ import annotations

import pytest

from app import music_analysis
from app.music_gate import (
    ANALYSER_OPENS_AT_RMS,
    GATE_DB_DEFAULT,
    GATE_DB_MAX,
    GATE_DB_MIN,
    LEGACY_RMS_PER_PERCENT,
    db_for_slider,
    format_db,
    gate_db_from_saved,
    rms_for_db,
    slider_for_db,
    slider_for_rms,
)


def test_the_slider_spans_minus_seventy_to_minus_ten_evenly():
    assert db_for_slider(0) == GATE_DB_MIN == -70.0
    assert db_for_slider(100) == GATE_DB_MAX == -10.0
    assert db_for_slider(50) == pytest.approx(-40.0)
    for value in (0, 23, 60, 87, 100):
        assert slider_for_db(db_for_slider(value)) == pytest.approx(value)


def test_silence_sits_at_the_bottom_and_nothing_runs_off_the_ends():
    assert slider_for_rms(0.0) == 0.0
    assert slider_for_rms(1e-9) == 0.0
    assert slider_for_rms(1.0) == 100.0


def test_an_old_percent_keeps_the_same_threshold():
    migrated = gate_db_from_saved({"gate": 16})
    assert migrated == pytest.approx(-33.98, abs=0.01)
    assert rms_for_db(migrated) == pytest.approx(16 * LEGACY_RMS_PER_PERCENT, rel=1e-3)
    assert gate_db_from_saved({"gate": 0}) == GATE_DB_MIN


def test_the_decibel_value_wins_and_bad_values_fall_back():
    assert gate_db_from_saved({"gate": 16, "gate_db": -45.0}) == -45.0
    assert gate_db_from_saved({"gate_db": -200}) == GATE_DB_MIN
    assert gate_db_from_saved({"gate_db": "loud"}) == GATE_DB_DEFAULT
    assert gate_db_from_saved({"gate_db": float("nan")}) == GATE_DB_DEFAULT


def test_a_new_installation_starts_at_the_analysers_own_lowest_threshold():
    assert gate_db_from_saved({}) == GATE_DB_DEFAULT
    assert ANALYSER_OPENS_AT_RMS == pytest.approx(music_analysis._MIN_FLOOR * music_analysis._OPEN_RATIO)
    assert GATE_DB_DEFAULT == pytest.approx(-56.1, abs=0.05)


def test_the_readout_uses_a_true_minus_sign():
    assert format_db(-56.2) == "−56"
    assert format_db(-10.0) == "−10"


@pytest.mark.parametrize("broken", [float("nan"), float("inf"), float("-inf"), "loud", None])
def test_a_broken_old_percent_falls_back_to_the_default(broken):
    assert gate_db_from_saved({"gate": broken}) == GATE_DB_DEFAULT

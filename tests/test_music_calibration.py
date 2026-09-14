"""Calibrating the microphone gate, fed synthetic rooms.

Each case is one of the rooms the gate has to be set in: digital silence from a
headset that suppresses its own noise, a steady fan, a room with one click, a
room with someone talking for part of it, a room with someone talking all the
way through, a microphone driven into clipping, and a device that sent nothing.
"""

from __future__ import annotations

import math

import pytest

from app.music_calibration import (
    CLIPPED,
    MEASURE_S,
    NO_AUDIO,
    OK,
    TOO_NOISY,
    UNSTABLE,
    WARMUP_S,
    NoiseSample,
    judge,
)
from app.music_gate import GATE_DB_DEFAULT, db_for_slider, rms_for_db

BLOCK_S = 1024 / 48000


def _record(levels, *, block_s=BLOCK_S, warmup=None, clipped_at=()):
    """Feed a sample the way the capture thread would: warm-up first, then the room."""
    sample = NoiseSample(session_token=1)
    for level in warmup if warmup is not None else [0.0] * math.ceil(WARMUP_S / block_s):
        sample.add(block_s, level, False)
    for index, level in enumerate(levels):
        sample.add(block_s, level, index in clipped_at)
    return sample


def _blocks(seconds=MEASURE_S, block_s=BLOCK_S):
    return math.ceil(seconds / block_s) + 1


def _judged(sample):
    return judge(*sample.snapshot())


def test_a_digitally_silent_headset_gets_the_analysers_own_lowest_threshold():
    result = _judged(_record([0.0] * _blocks()))
    assert result.outcome == OK
    assert GATE_DB_DEFAULT <= result.gate_db <= GATE_DB_DEFAULT + 0.6


def test_a_steady_room_gets_a_gate_just_above_it():
    room = rms_for_db(-60.0)
    result = _judged(_record([room] * _blocks()))
    assert result.outcome == OK
    assert -52.0 <= result.gate_db <= -52.0 + 0.6, "not eight decibels over the room, rounded up"
    assert result.gate_db == db_for_slider(result.position)


def test_a_room_measured_exactly_on_a_position_stays_on_it():
    import numpy as np

    # What a float32 sample of 0.001 really holds: a hair above -60 dB.
    room = float(np.float32(0.001))
    result = _judged(_record([room] * _blocks()))
    assert result.position == 30, "the last bits of a float32 pushed the gate a whole step"


def test_one_short_click_does_not_move_the_gate():
    room = rms_for_db(-60.0)
    levels = [room] * _blocks()
    levels[len(levels) // 2] = 0.3
    assert _judged(_record(levels)).gate_db == _judged(_record([room] * _blocks())).gate_db


def test_someone_talking_for_a_tenth_of_it_is_not_a_quiet_room():
    room, voice = rms_for_db(-60.0), rms_for_db(-28.0)
    levels = [room] * _blocks()
    for index in range(0, len(levels), 10):
        levels[index] = voice
    assert _judged(_record(levels)).outcome == UNSTABLE


def test_someone_talking_the_whole_time_is_too_noisy_to_calibrate_on():
    result = _judged(_record([rms_for_db(-25.0)] * _blocks()))
    assert result.outcome == TOO_NOISY
    assert result.position is None


def test_any_clipping_cancels_the_result():
    levels = [rms_for_db(-60.0)] * _blocks()
    assert _judged(_record(levels, clipped_at={40})).outcome == CLIPPED


def test_the_settling_half_second_is_thrown_away_pops_and_all():
    room = rms_for_db(-60.0)
    warm_up = [0.9] * math.ceil(WARMUP_S / BLOCK_S)
    sample = NoiseSample(session_token=1)
    for level in warm_up:
        sample.add(BLOCK_S, level, True)
    for level in [room] * _blocks():
        sample.add(BLOCK_S, level, False)
    assert _judged(sample).outcome == OK


def test_the_measurement_is_counted_in_audio_not_in_blocks():
    long_blocks = 0.1
    sample = _record([], block_s=long_blocks)
    for _ in range(math.ceil(MEASURE_S / long_blocks) - 1):
        sample.add(long_blocks, rms_for_db(-60.0), False)
    assert not sample.complete, "finished before three seconds of sound had arrived"
    sample.add(long_blocks, rms_for_db(-60.0), False)
    assert sample.complete


@pytest.mark.parametrize("levels", [[], [rms_for_db(-60.0)] * 5])
def test_a_device_that_sent_nothing_or_too_little_is_a_capture_error(levels):
    assert judge(levels, False, len(levels) * BLOCK_S).outcome == NO_AUDIO


_BROKEN = [math.nan, -math.inf, math.inf, -0.001]
_BROKEN_IDS = ["nan", "-inf", "inf", "negative"]


@pytest.mark.parametrize("bad", _BROKEN, ids=_BROKEN_IDS)
def test_a_level_that_is_not_a_level_is_a_broken_signal_not_a_quiet_room(bad):
    room = rms_for_db(-60.0)
    levels = [room] * _blocks()
    levels[len(levels) // 2] = bad
    assert judge(levels, False, MEASURE_S).outcome == NO_AUDIO, "one broken block hid in a quiet room"
    assert judge([bad] * _blocks(), False, MEASURE_S).outcome == NO_AUDIO, "a room of nothing but broken blocks"


@pytest.mark.parametrize("bad", _BROKEN, ids=_BROKEN_IDS)
@pytest.mark.parametrize("when", ["warm-up", "measurement"])
def test_a_broken_block_ends_the_measurement_at_once(bad, when):
    sample = NoiseSample(session_token=1)
    if when == "measurement":
        for _ in range(math.ceil(WARMUP_S / BLOCK_S) + 5):
            sample.add(BLOCK_S, rms_for_db(-60.0), False)
    sample.add(BLOCK_S, bad, False)
    assert sample.complete, "the measurement went on over a broken signal"
    assert _judged(sample).outcome == NO_AUDIO


def test_a_block_with_no_audio_in_it_is_no_time_in_the_room():
    sample = _record([])
    for _ in range(10 * _blocks()):
        sample.add(0.0, rms_for_db(-60.0), False)
    values, _clipped, measured = sample.snapshot()
    assert values == () and measured == 0.0, "empty blocks were counted as the room"
    assert not sample.complete

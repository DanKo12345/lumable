"""Silence and beats, fed synthetic blocks.

Every case here is one the old fixed threshold got wrong: a room that is merely
quiet read as music, a volume knob read as a drum, and a cooldown measured in
blocks rather than in time — which meant it changed with the sound card.
"""

from __future__ import annotations

import random

import pytest

from app.music_analysis import (
    ADAPTIVE_MAX_GAIN_DB,
    ADAPTIVE_RISE_DB_PER_S,
    LEVEL_CEILING,
    MIN_BEAT_GAP_MS,
    LoudnessReference,
    MusicAnalyzer,
)


def _quiet(analyzer: MusicAnalyzer, rms: float, blocks: int = 60, start: float = 0.0) -> float:
    """Let the analyzer learn what quiet sounds like here."""
    now = start
    for _ in range(blocks):
        analyzer.feed(bass=rms, mid=rms, treble=rms, rms=rms, now_ms=now)
        now += 20.0
    return now


def _block(
    analyzer: MusicAnalyzer,
    *,
    bass,
    mid,
    treble,
    rms,
    now,
    gate=0.0,
    beat_ratio=1.28,
):
    return analyzer.feed(
        bass=bass,
        mid=mid,
        treble=treble,
        rms=rms,
        now_ms=now,
        manual_gate=gate,
        beat_ratio=beat_ratio,
    )


# ── silence ───────────────────────────────────────────────────────────
def test_perfect_silence_never_reads_as_sound() -> None:
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.0, blocks=30)

    reading = _block(analyzer, bass=0.0, mid=0.0, treble=0.0, rms=0.0, now=now)

    assert reading.silent
    assert reading.level == 0.0


def test_a_steady_hiss_is_learned_and_ignored() -> None:
    """The failure that made this necessary: a card with a faint hiss had the
    strip twitching all evening, because the threshold was a constant chosen on
    somebody else's machine."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.004, blocks=120)

    reading = _block(analyzer, bass=0.004, mid=0.004, treble=0.004, rms=0.004, now=now)

    assert reading.silent, f"hiss was taken for sound, floor={reading.noise_floor}"
    assert reading.noise_floor > 0.0


def test_real_sound_above_a_learned_floor_still_gets_through() -> None:
    """A floor that ignores the hiss must not also ignore the music."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.004, blocks=120)

    reading = _block(analyzer, bass=0.05, mid=0.03, treble=0.02, rms=0.06, now=now)

    assert not reading.silent
    assert reading.level > 0.0


def test_the_edge_does_not_chatter() -> None:
    """A signal sitting on the threshold crosses it many times a second. It
    opens higher than it closes, so the strip does not flicker there."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.004, blocks=120)
    floor = analyzer.stats.noise_floor

    opened = _block(analyzer, bass=0.02, mid=0.01, treble=0.01, rms=floor * 3.0, now=now)
    assert not opened.silent

    # Now sit just under the level that opened it: still sound, because closing
    # takes a real drop.
    held = _block(analyzer, bass=0.02, mid=0.01, treble=0.01, rms=floor * 2.2, now=now + 20)
    assert not held.silent, "it closed at the same level it opened"

    gone = _block(analyzer, bass=0.0, mid=0.0, treble=0.0, rms=floor * 1.1, now=now + 40)
    assert gone.silent


def test_the_microphone_gate_can_only_make_it_stricter() -> None:
    """The slider is a minimum strictness on top of the measurement, not a
    replacement for it — turning it up can only ever make the app harder to
    trigger, which is what someone reaching for it wants."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=120)

    without = _block(analyzer, bass=0.01, mid=0.01, treble=0.01, rms=0.02, now=now)
    assert not without.silent

    analyzer.reset()
    now = _quiet(analyzer, 0.001, blocks=120)
    with_gate = _block(analyzer, bass=0.01, mid=0.01, treble=0.01, rms=0.02, now=now, gate=0.08)
    assert with_gate.silent, "a raised gate let quieter sound through"


def test_the_envelope_keeps_falling_in_silence() -> None:
    """Otherwise the strip goes on pulsing to a beat that has already passed."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=60)
    # A few sounding blocks first: the very first one only seeds what a normal
    # bass share looks like, so nothing can be an onset yet.
    for index in range(10):
        _block(analyzer, bass=0.2, mid=0.2, treble=0.2, rms=0.1, now=now + index * 20)
    now += 200
    hit = _block(analyzer, bass=0.9, mid=0.05, treble=0.05, rms=0.12, now=now)
    # Some strength, not full: how hard a strike registers now depends on how it
    # compares with the ones around it, and this is the first of the run. What
    # this test is about is what happens *after* it.
    assert hit.beat and hit.envelope > 0.0
    now += 200

    first = _block(analyzer, bass=0.0, mid=0.0, treble=0.0, rms=0.0, now=now)
    second = _block(analyzer, bass=0.0, mid=0.0, treble=0.0, rms=0.0, now=now + 20)

    assert second.envelope < first.envelope
    assert second.envelope >= 0.0


# ── beats ─────────────────────────────────────────────────────────────
def test_a_loud_flat_tone_is_not_a_drum() -> None:
    """Constant loudness with no rhythm: every block is as loud as the last, so
    nothing is an onset."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=40)

    beats = 0
    for index in range(200):
        reading = _block(
            analyzer, bass=0.3, mid=0.3, treble=0.3, rms=0.15, now=now + index * 20
        )
        beats += int(reading.beat)

    assert beats == 0, f"a steady tone produced {beats} beats"


def test_a_sustained_bass_line_becomes_the_new_normal() -> None:
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=40)

    beats = 0
    for index in range(200):
        reading = _block(
            analyzer, bass=0.9, mid=0.1, treble=0.05, rms=0.2, now=now + index * 20
        )
        beats += int(reading.beat)

    assert beats <= 1, f"heavy bass alone produced {beats} beats"


def test_turning_the_volume_up_is_not_a_beat() -> None:
    """The whole spectrum doubles. Bass as a share of the block is unchanged, so
    nothing was hit — this is the case a raw energy comparison gets wrong."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=40)
    for index in range(60):
        _block(analyzer, bass=0.2, mid=0.2, treble=0.2, rms=0.1, now=now + index * 20)
    now += 60 * 20

    beats = 0
    for index in range(60):
        reading = _block(
            analyzer, bass=0.8, mid=0.8, treble=0.8, rms=0.4, now=now + index * 20
        )
        beats += int(reading.beat)

    assert beats == 0, f"a volume change produced {beats} beats"


def test_regular_bass_hits_are_found() -> None:
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=40)

    beats = 0
    for index in range(80):
        hit = index % 8 == 0
        reading = _block(
            analyzer,
            bass=0.9 if hit else 0.15,
            mid=0.2,
            treble=0.2,
            rms=0.12,
            now=now + index * 60,
        )
        beats += int(reading.beat)

    assert 6 <= beats <= 10, f"found {beats} of about 10 kicks"


def test_bass_sensitivity_changes_which_onsets_count_as_beats() -> None:
    def marginal_hit(ratio: float) -> bool:
        analyzer = MusicAnalyzer()
        now = _quiet(analyzer, 0.001, blocks=40)
        for index in range(30):
            _block(
                analyzer,
                bass=0.2,
                mid=0.2,
                treble=0.2,
                rms=0.1,
                now=now + index * 20,
                beat_ratio=ratio,
            )
        return _block(
            analyzer,
            bass=0.3,
            mid=0.2,
            treble=0.2,
            rms=0.12,
            now=now + 700,
            beat_ratio=ratio,
        ).beat

    assert not marginal_hit(1.48)
    assert marginal_hit(1.08)


def test_one_hit_after_silence_is_one_beat() -> None:
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=60)
    for index in range(20):
        _block(analyzer, bass=0.2, mid=0.2, treble=0.2, rms=0.1, now=now + index * 20)
    now += 20 * 20

    first = _block(analyzer, bass=1.2, mid=0.2, treble=0.2, rms=0.3, now=now)
    following = sum(
        int(_block(analyzer, bass=0.2, mid=0.2, treble=0.2, rms=0.1, now=now + i * 20).beat)
        for i in range(1, 30)
    )

    assert first.beat
    assert following == 0, "one hit echoed into more"


def test_the_wait_between_beats_is_measured_in_time() -> None:
    """A block is not a unit of time: it changes with the sample rate and the
    buffer, so a cooldown counted in blocks means something different on every
    machine."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=40)
    for index in range(30):
        _block(analyzer, bass=0.2, mid=0.2, treble=0.2, rms=0.1, now=now + index * 5)
    now += 30 * 5

    first = _block(analyzer, bass=1.2, mid=0.2, treble=0.2, rms=0.3, now=now)
    too_soon = _block(
        analyzer, bass=1.4, mid=0.2, treble=0.2, rms=0.3, now=now + MIN_BEAT_GAP_MS * 0.4
    )

    assert first.beat
    assert not too_soon.beat, "a second beat landed inside the cooldown"


# ── starting over ─────────────────────────────────────────────────────
def test_a_reset_forgets_the_other_source() -> None:
    """A microphone's floor describes a room and a loopback's describes a silent
    digital line. Carrying one into the other leaves the strip either deaf or
    twitching."""
    analyzer = MusicAnalyzer()
    _quiet(analyzer, 0.02, blocks=200)
    loud_floor = analyzer.stats.noise_floor

    analyzer.reset()
    _quiet(analyzer, 0.0005, blocks=200)

    assert analyzer.stats.noise_floor < loud_floor / 4
    assert analyzer.stats.beats == 0
    assert analyzer.stats.blocks == 200, "the counters start again too"


def test_a_reset_clears_the_envelope_and_the_cooldown() -> None:
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=40)
    _block(analyzer, bass=1.2, mid=0.2, treble=0.2, rms=0.3, now=now)

    analyzer.reset()

    assert analyzer._env == 0.0
    assert analyzer._last_beat_ms is None


def test_the_counters_are_numbers_and_nothing_else() -> None:
    """The diagnostics block carries these. Nothing here is audio, a device or
    an application name."""
    analyzer = MusicAnalyzer()
    now = _quiet(analyzer, 0.001, blocks=10)
    _block(analyzer, bass=1.2, mid=0.2, treble=0.2, rms=0.3, now=now)

    stats = analyzer.stats
    assert stats.blocks == 11
    assert stats.silent_blocks >= 1
    assert isinstance(stats.noise_floor, float)
    assert 0.0 <= stats.peak_level <= 1.0


# ── where the floor starts ────────────────────────────────────────────
_QUIET_MUSIC = 10 ** (-44 / 20)


def _steady_music(analyzer: MusicAnalyzer, seconds: float = 120.0) -> list:
    """Quiet music from the very first block, never pausing: -44 dBFS, give or
    take the two decibels a real track moves."""
    import random

    rng = random.Random(7)
    readings = []
    for index in range(int(seconds * 1000 / 20)):
        rms = _QUIET_MUSIC * 10 ** (rng.uniform(-2.0, 2.5) / 20)
        readings.append(_block(analyzer, bass=rms, mid=rms, treble=rms * 0.5, rms=rms, now=index * 20.0))
    return readings


def test_music_already_playing_on_a_digital_line_is_heard_from_the_first_block() -> None:
    analyzer = MusicAnalyzer()
    analyzer.reset(digital=True)

    readings = _steady_music(analyzer)

    heard = sum(not reading.silent for reading in readings)
    assert heard == len(readings), f"{len(readings) - heard} of {len(readings)} blocks taken for silence"


def test_digital_zero_stays_silence_on_a_digital_line() -> None:
    analyzer = MusicAnalyzer()
    analyzer.reset(digital=True)
    now = _quiet(analyzer, 0.0, blocks=200)

    reading = _block(analyzer, bass=0.0, mid=0.0, treble=0.0, rms=0.0, now=now)

    assert reading.silent
    assert reading.level == 0.0


def test_a_microphone_still_learns_its_room_from_the_first_block() -> None:
    """Unchanged for the microphone: what it hears first is the room, and a room
    that steady is not sound."""
    analyzer = MusicAnalyzer()
    analyzer.reset()

    readings = _steady_music(analyzer, seconds=10.0)

    assert all(reading.silent for reading in readings), "a steady room was taken for sound"
    assert readings[-1].noise_floor > 2 * _QUIET_MUSIC / 3, "the floor was not learned from the room"


# ── lifting quiet system music ────────────────────────────────────────
_SPAN = LEVEL_CEILING - 0.0006 * 1.7  # a digital line's scale above its gate
_BLOCK_MS = 1024 / 48000 * 1000


def _tune(seconds, level_db, *, start_ms=0.0, step_ms=_BLOCK_MS, spread_db=2.5, kicks=True, beat_s=0.5, seed=1):
    """RMS of a track, block by block: a kick every ``beat_s`` seconds, lasting 60 ms."""
    rng = random.Random(seed)
    blocks = []
    for index in range(int(seconds * 1000 / step_ms)):
        now = start_ms + index * step_ms
        kick = kicks and beat_s and now % (beat_s * 1000.0) < 60.0
        value = level_db + rng.uniform(-spread_db, spread_db) + (6.0 if kick else 0.0)
        blocks.append((now, 10 ** (value / 20), False))
    return blocks


def _pause(seconds, *, start_ms, step_ms=_BLOCK_MS):
    return [(start_ms + index * step_ms, 0.0, True) for index in range(int(seconds * 1000 / step_ms))]


def _lift(blocks, reference=None):
    reference = reference or LoudnessReference()
    gains = []
    for now, excess, silent in blocks:
        reference.update(excess, silent=silent, now_ms=now)
        gains.append((now, reference.gain_db(_SPAN)))
    return reference, gains


def test_quiet_system_music_is_lifted_at_once() -> None:
    blocks = _tune(0.5, -44.0, spread_db=0.0, kicks=False)
    _, gains = _lift(blocks)

    excess = blocks[-1][1]
    before = (excess / _SPAN) ** 0.5
    after = min(1.0, excess * 10 ** (gains[-1][1] / 20) / _SPAN) ** 0.5
    assert gains[0][1] == ADAPTIVE_MAX_GAIN_DB, "the first block heard did not set the lift"
    assert after >= 0.6 and after > 3 * before, f"quiet music stayed dim: {before:.2f} -> {after:.2f}"


@pytest.mark.parametrize("level_db", [-12.0, -9.0])
def test_music_that_already_fills_the_scale_is_never_turned_down(level_db) -> None:
    _, gains = _lift(_tune(30, level_db))

    assert max(gain for _, gain in gains) == 0.0


def test_the_lift_stops_at_its_limit_however_quiet_the_music() -> None:
    _, gains = _lift(_tune(10, -70.0))

    assert all(0.0 <= gain <= ADAPTIVE_MAX_GAIN_DB for _, gain in gains)
    assert gains[-1][1] == ADAPTIVE_MAX_GAIN_DB


def test_digital_zero_lifts_nothing() -> None:
    _, gains = _lift(_pause(5, start_ms=0.0))

    assert all(gain == 0.0 for _, gain in gains)


def test_a_pause_keeps_the_lift_and_is_not_counted_as_time_heard() -> None:
    reference, before = _lift(_tune(10, -30.0, seed=2))
    kept = before[-1][1]
    assert kept > 3.0, "the test needs a lift worth keeping"

    _, during = _lift(_pause(10, start_ms=10_000.0), reference)
    assert all(gain == kept for _, gain in during), "the lift moved in silence"

    # The music comes back far louder. Ten seconds of pause are not ten seconds
    # of hearing it: the first block moves nothing, the next ones move at the
    # rising speed and no faster.
    _, after = _lift(_tune(1, -12.0, start_ms=20_000.0, seed=3, spread_db=0.0, kicks=False), reference)
    assert after[0][1] == kept, "the pause was counted as time the music was heard"
    assert kept - after[4][1] <= ADAPTIVE_RISE_DB_PER_S * 4 * _BLOCK_MS / 1000 + 1e-9


def test_a_louder_track_is_over_lit_for_under_a_second() -> None:
    reference, _ = _lift(_tune(20, -40.0, seed=4))
    _, gains = _lift(_tune(20, -12.0, start_ms=20_000.0, seed=5), reference)

    still_lifted = [now for now, gain in gains if gain > 1.0]
    assert not still_lifted or max(still_lifted) - 20_000.0 <= 1000.0


def test_a_quieter_track_is_lifted_again_within_eight_seconds() -> None:
    reference, _ = _lift(_tune(20, -14.0, seed=6))
    _, gains = _lift(_tune(60, -36.0, start_ms=20_000.0, seed=7), reference)

    final = gains[-1][1]
    assert 0.0 < final < ADAPTIVE_MAX_GAIN_DB, "the test needs a lift away from both limits"
    reached = next(now for now, gain in gains if gain >= 0.9 * final)
    assert reached - 20_000.0 <= 8_000.0, f"took {(reached - 20_000.0) / 1000:.1f} s"


_GATE = 0.0006 * 1.7


def _smoothed(blocks, reactivity=0.35):
    """What the controller hands the reference: the RMS eased at the default
    speed, measured above the gate."""
    eased, out = None, []
    for now, rms, silent in blocks:
        eased = rms if eased is None else eased + (rms - eased) * reactivity
        out.append((now, max(0.0, eased - _GATE), silent))
    return out


def _rooms(level_db, beat_s):
    return _smoothed(_tune(40, level_db, beat_s=beat_s, seed=int(-level_db * 10 + beat_s * 10)))


_LEVELS = [-36.0, -30.0, -24.0]


@pytest.mark.parametrize("beat_s", [0.5, 1.2, 0.0], ids=["beat every 0.5 s", "beat every 1.2 s", "no beat"])
@pytest.mark.parametrize("level_db", _LEVELS)
def test_the_lift_does_not_pump_with_the_music(level_db, beat_s) -> None:
    # Measured where no limit can flatten it. A lift pinned at +24 dB does not
    # move whatever the reference does: that is how a reference chasing peaks
    # once passed at 0.3 dB while swinging 2.5 dB everywhere else.
    _, gains = _lift(_rooms(level_db, beat_s))
    settled = [(now, gain) for now, gain in gains if now >= 3000.0]
    assert all(0.0 < gain < ADAPTIVE_MAX_GAIN_DB for _, gain in settled), "the lift touched a limit"

    worst, first = 0.0, 0
    for index, (now, _gain) in enumerate(settled):
        while settled[first][0] < now - 500.0:
            first += 1
        window = [gain for _, gain in settled[first:index + 1]]
        worst = max(worst, max(window) - min(window))
    assert worst <= 1.1, f"the lift swung {worst:.2f} dB within half a second"


@pytest.mark.parametrize("beat_s", [0.5, 1.2], ids=["beat every 0.5 s", "beat every 1.2 s"])
@pytest.mark.parametrize("level_db", _LEVELS)
def test_a_beat_keeps_its_size_under_the_lift(level_db, beat_s) -> None:
    """The lift must not eat the beat it lifts: each kick raises the lifted
    level nearly as far as it would under a lift held where it was."""
    blocks = _rooms(level_db, beat_s)
    _, gains = _lift(blocks)
    period_ms = beat_s * 1000.0

    def level(index, gain_db):
        return min(1.0, blocks[index][1] * 10 ** (gain_db / 20) / _SPAN) ** 0.5

    live_rise = held_rise = 0.0
    for index in range(1, len(blocks) - 8):
        now, before = blocks[index][0], blocks[index - 1][0]
        if now < 3000.0 or not (now % period_ms < 60.0 <= before % period_ms):
            continue
        held = gains[index - 1][1]
        base = level(index - 1, held)
        live_rise += max(level(i, gains[i][1]) for i in range(index, index + 8)) - base
        held_rise += max(level(i, held) for i in range(index, index + 8)) - base
    assert held_rise > 0.0, "the test needs beats"
    assert live_rise >= 0.8 * held_rise, f"the lift ate {1 - live_rise / held_rise:.0%} of the beat"


def test_the_lift_is_timed_in_seconds_not_in_blocks() -> None:
    finals = []
    for step_ms in (5.0, _BLOCK_MS):
        reference, _ = _lift(_tune(10, -14.0, step_ms=step_ms, spread_db=0.0, kicks=False))
        _, gains = _lift(_tune(5, -30.0, start_ms=10_000.0, step_ms=step_ms, spread_db=0.0, kicks=False), reference)
        finals.append(gains[-1][1])

    assert abs(finals[0] - finals[1]) <= 0.5, f"same music, different blocks: {finals}"


def test_a_reset_forgets_the_lift() -> None:
    reference, gains = _lift(_tune(5, -44.0))
    assert gains[-1][1] > 0.0

    reference.reset()

    assert reference.gain_db(_SPAN) == 0.0

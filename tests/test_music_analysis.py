"""Silence and beats, fed synthetic blocks.

Every case here is one the old fixed threshold got wrong: a room that is merely
quiet read as music, a volume knob read as a drum, and a cooldown measured in
blocks rather than in time — which meant it changed with the sound card.
"""

from __future__ import annotations

from app.music_analysis import MIN_BEAT_GAP_MS, MusicAnalyzer


def _quiet(analyzer: MusicAnalyzer, rms: float, blocks: int = 60, start: float = 0.0) -> float:
    """Let the analyzer learn what quiet sounds like here."""
    now = start
    for _ in range(blocks):
        analyzer.feed(bass=rms, mid=rms, treble=rms, rms=rms, now_ms=now)
        now += 20.0
    return now


def _block(analyzer: MusicAnalyzer, *, bass, mid, treble, rms, now, gate=0.0):
    return analyzer.feed(
        bass=bass, mid=mid, treble=treble, rms=rms, now_ms=now, manual_gate=gate
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

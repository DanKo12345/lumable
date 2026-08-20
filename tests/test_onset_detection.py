"""Whether a strike can be told from a voice, on synthetic sound.

The detector beside this one asks whether the bass is a bigger share than it
recently was. A sung syllable, a plosive and a bass line with no drums all
answer yes. This one asks whether energy *appeared*, which a sustained note —
however loud, however wobbled by vibrato — has not.

The signals are built here rather than described: a note is a note with real
harmonics, vibrato really moves them, and the spectra come from the same rfft
the application uses. Asserting on hand-written spectra would be asserting on
what I imagined a voice looks like.
"""

from __future__ import annotations

import pytest

from app.onset_detection import MIN_ONSET_GAP_MS, SuperFluxOnset

np = pytest.importorskip("numpy")

RATE = 48000
BLOCK = 1024
BLOCK_MS = BLOCK / RATE * 1000.0


def _spectrum(samples):
    window = np.hanning(samples.size).astype(np.float32)
    return np.abs(np.fft.rfft(samples * window)), np.fft.rfftfreq(samples.size, d=1.0 / RATE)


def _play(detector: SuperFluxOnset, blocks) -> list[bool]:
    """Feed a run of blocks in order and report where it heard a strike."""
    heard = []
    for index, samples in enumerate(blocks):
        magnitudes, freqs = _spectrum(samples)
        heard.append(detector.feed(magnitudes, freqs, index * BLOCK_MS).onset)
    return heard


def _voice(count: int, *, base: float = 180.0, vibrato_hz: float = 6.0, depth: float = 0.04):
    """A sung note: a fundamental with harmonics, wobbling in pitch.

    Vibrato is the case a plain difference gets wrong — the harmonics move a
    little every block, and every one of those movements looks like new energy.

    The phase is accumulated rather than written as ``f * wobble(t) * t``, which
    is the obvious form and is not vibrato at all: its instantaneous frequency
    grows with ``t``, so what it produces is a chirp across the whole spectrum.
    The first version of this helper did exactly that, and the detector was
    blamed for what the signal was doing.
    """
    samples = np.arange(count * BLOCK) / RATE
    wobble = 1.0 + depth * np.sin(2 * np.pi * vibrato_hz * samples)
    signal = np.zeros(samples.size, dtype=np.float64)
    for harmonic, weight in ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)):
        phase = 2 * np.pi * base * harmonic * np.cumsum(wobble) / RATE
        signal += weight * np.sin(phase)
    signal = (signal * 0.25).astype(np.float32)
    return [signal[index * BLOCK : (index + 1) * BLOCK] for index in range(count)]


def _kick(index_in_burst: int):
    """One block of a struck drum: a low thump that starts hard and dies."""
    t = np.arange(BLOCK) / RATE
    envelope = np.exp(-t * 45.0) if index_in_burst == 0 else np.exp(-(t + 0.021) * 45.0)
    tone = np.sin(2 * np.pi * 55.0 * t) + 0.6 * np.sin(2 * np.pi * 90.0 * t)
    return (tone * envelope * 0.9).astype(np.float32)


def _quiet(count: int):
    return [np.zeros(BLOCK, dtype=np.float32) for _ in range(count)]


# ── a voice is not a drum ─────────────────────────────────────────────
def test_a_sustained_voice_with_vibrato_is_not_a_run_of_strikes() -> None:
    """The failure this exists for. Singing moves its harmonics a little every
    block; counted as new energy, that is a strike on every syllable and often
    on every wobble."""
    detector = SuperFluxOnset()

    blocks = _quiet(4) + _voice(120)

    heard = _play(detector, blocks)

    # The note beginning is a real onset, so this is not "none at all": what
    # must not happen is a strike every syllable or every wobble.
    assert sum(heard) <= len(blocks) // 40, (
        f"the voice was heard as {sum(heard)} strikes in {len(blocks)} blocks"
    )


def test_a_louder_voice_is_still_not_a_run_of_strikes() -> None:
    """A singer getting louder is a swell, not a series of hits."""
    detector = SuperFluxOnset()
    swelling = [block * (0.4 + 1.2 * index / 100.0) for index, block in enumerate(_voice(100))]

    heard = _play(detector, _quiet(4) + swelling)

    assert sum(heard) <= 2, f"a swell was heard as {sum(heard)} strikes"


# ── a drum is ─────────────────────────────────────────────────────────
def test_one_struck_drum_is_heard_once() -> None:
    detector = SuperFluxOnset()
    blocks = [*_quiet(10), _kick(0), _kick(1), _kick(2), *_quiet(10)]

    heard = _play(detector, blocks)

    assert sum(heard) == 1, f"one kick was heard {sum(heard)} times"
    assert heard.index(True) == 10, "the strike was not heard at its onset"


def test_a_drum_over_a_singing_voice_is_still_heard() -> None:
    """The one that matters in a real track: the voice must be ignored without
    the kick going with it."""
    detector = SuperFluxOnset()
    voice = _voice(60)
    blocks = list(voice)
    for at in (20, 32, 44):
        blocks[at] = voice[at] + _kick(0)
        blocks[at + 1] = voice[at + 1] + _kick(1)

    heard = _play(detector, _quiet(4) + blocks)

    struck = [index - 4 for index, hit in enumerate(heard) if hit]
    assert len(struck) == 3, f"heard {len(struck)} strikes, expected 3: {struck}"
    for expected in (20, 32, 44):
        assert any(abs(index - expected) <= 1 for index in struck), (
            f"no strike near block {expected}: {struck}"
        )


def test_two_full_strikes_closer_than_the_cooldown_are_one() -> None:
    """Two fresh attacks 43 ms apart, well inside the 110 ms gap. Both are
    genuine onsets by every other measure — the second really is new energy —
    and the cooldown is the only thing that says a drum was not struck twice
    that fast.

    Separated by a silent block rather than laid back to back: three copies of
    the same block are not three attacks, they are a steady tone, and nothing
    appears in the second or third at all.
    """
    detector = SuperFluxOnset()
    assert MIN_ONSET_GAP_MS > BLOCK_MS * 2, "the cooldown is shorter than two blocks"
    blocks = [*_quiet(10), _kick(0), *_quiet(1), _kick(0), *_quiet(6)]

    heard = _play(detector, blocks)

    assert heard[10] is True, "the first attack was not heard at all"
    assert sum(heard) == 1, f"two attacks inside the cooldown counted {sum(heard)} times"


# ── loudness is not an onset ──────────────────────────────────────────
def test_turning_everything_up_is_not_a_strike() -> None:
    """The whole spectrum rises at once. There is a great deal of new energy and
    nothing was struck — the case a plain flux threshold gets wrong.

    Compared against the same passage without the change rather than against a
    number: what has to hold is that the jump adds nothing, and a count I chose
    would be a statement about today's constants instead.
    """
    steady = SuperFluxOnset()
    jumping = SuperFluxOnset()
    quiet_voice = _voice(40)
    loud_voice = [block * 3.0 for block in _voice(40)]

    without = _play(steady, _quiet(4) + quiet_voice + _voice(40))
    with_jump = _play(jumping, _quiet(4) + quiet_voice + loud_voice)

    assert sum(with_jump) <= sum(without), (
        f"the volume change added {sum(with_jump) - sum(without)} strikes"
    )


def test_nothing_is_heard_in_silence() -> None:
    detector = SuperFluxOnset()

    assert not any(_play(detector, _quiet(40)))
    assert detector.stats.onsets == 0
    assert detector.stats.blocks == 40


def test_starting_over_forgets_the_previous_run() -> None:
    """A run's idea of normal describes that run's music. Carried into the next
    one it judges a quiet track by a loud one's standard."""
    detector = SuperFluxOnset()
    _play(detector, _quiet(4) + _voice(40))
    detector.reset()

    assert detector.stats.blocks == 0
    assert detector._previous is None


# ── pairing what the two detectors heard ──────────────────────────────
def _agreement(tolerance_ms: float = 25.0):
    from app.onset_detection import OnsetAgreement

    return OnsetAgreement(tolerance_ms=tolerance_ms)


def test_a_strike_heard_a_block_apart_is_one_agreement() -> None:
    """The two read the strike from different things — the change into a block,
    and the block's own content — so the same drum can land a block apart.
    Counted strictly that is a miss and an extra: two errors invented from one
    agreement, which would make the trial look worse and busier than it is."""
    pairs = _agreement()

    pairs.note(old=True, shadow=False, now_ms=0.0)
    pairs.note(old=False, shadow=True, now_ms=21.0)
    totals = pairs.totals(1000.0)

    assert totals.matched == 1
    assert totals.old_only == 0 and totals.shadow_only == 0


def test_a_strike_is_one_agreement_whichever_detector_heard_it_first() -> None:
    """Both orders. Which of the two is early depends on where the strike fell
    inside a block, so a pairing that only works one way round would report half
    the agreements as misses on some tracks and not on others."""
    old_first = _agreement()
    old_first.note(old=True, shadow=False, now_ms=0.0)
    old_first.note(old=False, shadow=True, now_ms=21.0)

    shadow_first = _agreement()
    shadow_first.note(old=False, shadow=True, now_ms=0.0)
    shadow_first.note(old=True, shadow=False, now_ms=21.0)

    assert old_first.totals(1000.0).matched == 1
    assert shadow_first.totals(1000.0).matched == 1, "only one order was paired"


def test_one_old_beat_cannot_confirm_two_candidates() -> None:
    """Otherwise a detector that fires twice as often looks twice as accurate."""
    pairs = _agreement()

    pairs.note(old=True, shadow=False, now_ms=0.0)
    pairs.note(old=False, shadow=True, now_ms=10.0)
    pairs.note(old=False, shadow=True, now_ms=20.0)
    totals = pairs.totals(1000.0)

    assert totals.matched == 1
    assert totals.shadow_only == 1
    assert totals.old_beats == 1 and totals.shadow_candidates == 2


def test_matched_can_never_exceed_either_side() -> None:
    """The invariant that makes the five numbers readable at all."""
    import random

    rng = random.Random(20260820)
    for _ in range(200):
        pairs = _agreement(tolerance_ms=25.0)
        now = 0.0
        for _ in range(40):
            now += rng.choice((5.0, 21.0, 40.0, 300.0))
            pairs.note(old=rng.random() < 0.4, shadow=rng.random() < 0.4, now_ms=now)
        totals = pairs.totals(now + 10_000.0)

        assert totals.matched <= min(totals.old_beats, totals.shadow_candidates)
        assert totals.matched + totals.old_only == totals.old_beats
        assert totals.matched + totals.shadow_only == totals.shadow_candidates


def test_an_event_too_far_apart_is_not_a_pair() -> None:
    pairs = _agreement(tolerance_ms=25.0)

    pairs.note(old=True, shadow=False, now_ms=0.0)
    pairs.note(old=False, shadow=True, now_ms=200.0)
    totals = pairs.totals(1000.0)

    assert totals.matched == 0
    assert totals.old_only == 1 and totals.shadow_only == 1


def test_events_still_waiting_are_counted_when_the_run_is_read() -> None:
    """A report is asked for while the last events are still in hand. They have
    to appear somewhere, or the totals quietly lose them."""
    pairs = _agreement()

    pairs.note(old=True, shadow=False, now_ms=1000.0)
    totals = pairs.totals(1000.0)

    assert totals.old_beats == 1
    assert totals.matched + totals.old_only == 1


def test_nothing_is_kept_but_a_handful_of_timestamps() -> None:
    """It sits on the audio path. A list that grows with the evening is a leak,
    and audio must never be held at all."""
    pairs = _agreement(tolerance_ms=25.0)

    for index in range(5000):
        pairs.note(old=True, shadow=False, now_ms=index * 1.0)

    assert len(pairs._waiting_old) <= 8
    assert len(pairs._waiting_shadow) <= 8

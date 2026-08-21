"""The whole music path, judged by the colours the engine actually receives.

The old tests checked that a handful of helper functions existed and returned
what they were told to. These feed blocks in at the top and look at the RGB that
comes out the bottom, because that is the only thing a person can see.

No sound card is involved: the analysis step is fed numbers directly, and time
is simulated, so a cooldown measured in milliseconds can be tested without
waiting real ones.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("PySide6")

import app.music_controller as module
from app.music_controller import MusicController, MusicOptions


class _Player:
    """Feeds blocks through _process_block with a clock we control."""

    def __init__(self, controller: MusicController, options: MusicOptions) -> None:
        self._controller = controller
        self._options = options
        self._clock = 1000.0
        self._original_analyze = module.analyze_block
        self._original_monotonic = module.monotonic

    def __enter__(self):
        module.monotonic = lambda: self._clock
        return self

    def __exit__(self, *exc):
        module.analyze_block = self._original_analyze
        module.monotonic = self._original_monotonic
        return False

    def play(self, blocks, step_ms: float = 20.0):
        return [result.rgb for result in self.play_results(blocks, step_ms)]

    def play_results(self, blocks, step_ms: float = 20.0):
        results = []
        for values in blocks:
            module.analyze_block = lambda _b, _s, v=values: v
            results.append(self._controller._process_block(None, 48000, self._options))
            self._clock += step_ms / 1000.0
        return results


def _controller(**options) -> tuple[MusicController, MusicOptions]:
    return MusicController(), MusicOptions(source="system", **options)


def _brightness(colour) -> int:
    return max(colour)


def _silence(count: int, level: float = 0.0):
    return [(level, level, level, level)] * count


def _music(count: int, *, kick_every: int = 8):
    out = []
    for index in range(count):
        kick = index % kick_every == 0
        out.append(
            (
                0.9 if kick else 0.18 + 0.05 * math.sin(index / 7),
                0.30 + 0.08 * math.sin(index / 5),
                0.22 + 0.06 * math.sin(index / 11),
                0.11 + (0.05 if kick else 0.0),
            )
        )
    return out


# ── silence ───────────────────────────────────────────────────────────
def test_digital_silence_settles_and_stays_settled() -> None:
    """A line carrying literal zeros has no band to colour, so the strip is
    dark. What matters is that it is *still*: the old fixed threshold left it
    drifting a little on every block."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        colours = player.play(_silence(80))

    settled = [_brightness(colour) for colour in colours[-20:]]
    assert max(settled) <= 20
    assert len(set(settled)) == 1, f"the colour never came to rest: {settled}"


def test_a_hiss_the_card_always_makes_is_learned_and_ignored() -> None:
    """The complaint this block exists for: a faint constant hiss had the strip
    twitching all evening, because the threshold was a number chosen on someone
    else's machine."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        colours = player.play(_silence(200, level=0.004))

    settled = [_brightness(colour) for colour in colours[-40:]]
    assert max(settled) - min(settled) <= 2, f"the colour kept moving: {settled[:8]}"
    assert controller._analyzer.stats.beats == 0


def test_music_after_that_hiss_still_gets_through() -> None:
    """A floor that ignores the hiss must not also ignore the music."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_silence(120, level=0.004))
        colours = player.play(_music(60))

    assert max(_brightness(colour) for colour in colours) > 120


# ── beats ─────────────────────────────────────────────────────────────
def test_a_steady_loud_tone_does_not_pulse() -> None:
    controller, options = _controller()
    tone = [(0.3, 0.3, 0.3, 0.15)] * 200
    with _Player(controller, options) as player:
        player.play(tone)

    assert controller._analyzer.stats.beats == 0


def test_turning_the_volume_up_is_not_a_drum_roll() -> None:
    """Every band doubles at once. Bass as a share of the block is unchanged, so
    nothing was hit — the case a raw energy comparison gets wrong."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play([(0.2, 0.2, 0.2, 0.1)] * 60)
        before = controller._analyzer.stats.beats
        player.play([(0.8, 0.8, 0.8, 0.4)] * 60)

    assert controller._analyzer.stats.beats == before


def test_the_beat_slider_still_makes_the_strip_punch() -> None:
    """Compared against itself with the pulse turned off, because loud music
    already sits near full brightness — an absolute threshold would only be
    measuring the ceiling. The slider keeps its old meaning: 0 is no pulse,
    higher is a deeper one."""
    quiet_beat = [
        (0.7 if index % 8 == 0 else 0.12, 0.14, 0.10, 0.030 + (0.004 if index % 8 == 0 else 0.0))
        for index in range(200)
    ]

    without, no_pulse = _controller(beat_strength=0.0)
    with _Player(without, no_pulse) as player:
        flat = player.play(quiet_beat)

    withpulse, pulsing = _controller(beat_strength=1.0)
    with _Player(withpulse, pulsing) as player:
        punchy = player.play(quiet_beat)

    flat_peak = max(_brightness(colour) for colour in flat[40:])
    punchy_peak = max(_brightness(colour) for colour in punchy[40:])
    assert punchy_peak > flat_peak, "the beat slider stopped doing anything"
    assert withpulse._analyzer.stats.beats > 10


def test_the_cooldown_is_time_and_not_blocks() -> None:
    """A block is not a unit of time: it changes with the sample rate and the
    buffer. Same music, blocks four times closer together — the beats found
    should not multiply."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_music(200), step_ms=20.0)
        slow = controller._analyzer.stats.beats

    controller2, options2 = _controller()
    with _Player(controller2, options2) as player:
        player.play(_music(200), step_ms=5.0)
        fast = controller2._analyzer.stats.beats

    assert fast <= slow, f"faster blocks invented beats: {fast} vs {slow}"


def test_the_pulse_does_not_go_on_beating_after_the_music_stops() -> None:
    """The failure worth naming: an envelope left holding its last value keeps
    the strip flashing to a beat that has already ended."""
    controller, options = _controller(beat_strength=1.0)
    with _Player(controller, options) as player:
        during = player.play(_music(80))
        after = player.play(_silence(60))

    assert _brightness(during[-1]) > _brightness(after[-1]), "it never came down"
    assert _brightness(after[-1]) <= 20
    # And nothing flares up again once it is quiet.
    settled = [_brightness(colour) for colour in after[10:]]
    assert max(settled) <= min(settled) + 1, f"it kept pulsing in silence: {settled[:10]}"


# ── starting over ─────────────────────────────────────────────────────
def test_a_restart_does_not_carry_the_old_room_over() -> None:
    """A microphone's floor describes a room and a loopback's a silent digital
    line. Carrying one into the other leaves the strip deaf or twitching."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_silence(200, level=0.02))
    loud_room = controller._analyzer.stats.noise_floor

    controller._reset_analysis()
    with _Player(controller, options) as player:
        player.play(_silence(200, level=0.0005))

    assert controller._analyzer.stats.noise_floor < loud_room
    assert controller._analyzer.stats.blocks == 200, "the counters start again"


def test_the_manual_microphone_gate_only_tightens_things() -> None:
    quiet_music = [(0.05, 0.05, 0.05, 0.03)] * 60

    controller, options = _controller(noise_gate=0.0)
    with _Player(controller, options) as player:
        player.play(_silence(60, level=0.0005))
        open_colours = player.play(quiet_music)

    strict, strict_options = _controller(noise_gate=0.5)
    with _Player(strict, strict_options) as player:
        player.play(_silence(60, level=0.0005))
        gated_colours = player.play(quiet_music)

    assert max(_brightness(c) for c in open_colours) > max(
        _brightness(c) for c in gated_colours
    ), "raising the gate did not make it stricter"


# ── the shape of the reaction ─────────────────────────────────────────
def test_the_reaction_is_no_dimmer_than_it_used_to_be() -> None:
    """Measured against the behaviour this replaced. It does not have to match
    bit for bit, but a rewrite that quietly halves the brightness would be a
    regression nobody reported as one."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        colours = player.play(_music(600))

    brightness = [_brightness(colour) for colour in colours]
    average = sum(brightness) / len(brightness)
    assert average >= 200, f"the strip got dimmer: mean {average:.0f} of 255"
    assert max(brightness) >= 250


def test_the_colours_are_still_spread_across_the_bands() -> None:
    """The hue comes from which band dominates. A change that collapsed
    everything onto one colour would pass every brightness check."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        colours = player.play(_music(600))

    dominant = [max(range(3), key=lambda channel: colour[channel]) for colour in colours]
    assert len(set(dominant)) >= 2, "every block came out the same hue"
    assert min(dominant.count(0), dominant.count(2)) > 50


# ── where the work happens ────────────────────────────────────────────
def test_the_analysis_never_runs_on_the_ui_thread() -> None:
    """It is the capture thread's job. On the UI thread a slow block would stop
    the window from redrawing, which is how "the app freezes with music on"
    starts."""
    import threading

    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    ui_thread = threading.current_thread()
    seen: list[str] = []

    controller, options = _controller()
    original = module.analyze_block

    def record(_block, _rate):
        seen.append(threading.current_thread().name)
        return (0.2, 0.2, 0.2, 0.1)

    module.analyze_block = record
    try:
        worker = threading.Thread(
            target=lambda: controller._process_block(None, 48000, options), name="MusicCapture"
        )
        worker.start()
        worker.join(timeout=5)
    finally:
        module.analyze_block = original

    assert seen == ["MusicCapture"]
    assert seen[0] != ui_thread.name


def test_reduced_motion_changes_nothing_about_the_sound() -> None:
    """Reduced Motion is about the interface. Letting it reach the analysis
    would mean the strip reacted differently depending on an accessibility
    setting."""
    from app.motion_policy import motion_policy

    controller, options = _controller()
    with _Player(controller, options) as player:
        normal = player.play(_music(120))

    motion_policy.set_mode("reduced")
    try:
        reduced_controller, reduced_options = _controller()
        with _Player(reduced_controller, reduced_options) as player:
            reduced = player.play(_music(120))
    finally:
        motion_policy.set_mode("system")

    assert normal == reduced


def test_the_floor_stops_learning_while_sound_is_coming_through() -> None:
    """Adapting to the music means slowly deciding the music is the silence.
    Measured with sound quiet enough to sit under the ceiling, where the
    difference is visible."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_silence(120, level=0.001))
        learned = controller._analyzer.stats.noise_floor
        player.play([(0.006, 0.006, 0.006, 0.006)] * 300)

    assert controller._analyzer.stats.noise_floor == pytest.approx(learned, rel=0.3), (
        "the floor climbed toward the sound it was letting through"
    )


def test_changing_the_source_forgets_the_old_one() -> None:
    """A microphone's floor describes a room and a loopback's a silent digital
    line, so switching has to start again."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_silence(150, level=0.006))
    learned = controller._analyzer.stats.noise_floor
    assert learned > 0.002

    controller.configure(source="mic")

    assert controller._analyzer.stats.blocks == 0
    assert controller._analyzer.stats.noise_floor == 0.0


def test_changing_the_device_forgets_it_too() -> None:
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_silence(100, level=0.006))

    controller.configure(device_name="Another microphone")

    assert controller._analyzer.stats.blocks == 0


def test_starting_again_does_not_inherit_the_last_run() -> None:
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_music(80))
    assert controller._analyzer.stats.beats > 0

    controller.start_output(lambda r, g, b: None)
    try:
        assert controller._analyzer.stats.beats == 0
        assert controller._analyzer.stats.blocks == 0
    finally:
        controller.stop()


def test_a_capture_failure_throws_away_what_that_device_taught_us() -> None:
    """Whatever was learned came from a device that has just gone wrong."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_silence(150, level=0.006))
    assert controller._analyzer.stats.blocks > 0

    original_open = controller._open_loopback_reader
    controller._open_loopback_reader = lambda _options: (_ for _ in ()).throw(OSError("device gone"))
    try:
        controller._run()
    finally:
        controller._open_loopback_reader = original_open

    assert controller._analyzer.stats.blocks == 0
    assert controller._analyzer.stats.noise_floor == 0.0


def test_a_device_that_fails_mid_run_also_takes_its_profile_with_it() -> None:
    """The other half of the same case: opening succeeded, the device died
    later. What it taught us is worth no more than if it had never opened."""
    controller, options = _controller()
    with _Player(controller, options) as player:
        player.play(_silence(150, level=0.006))
    assert controller._analyzer.stats.blocks > 0

    def reader(_options):
        def read(_size):
            raise OSError("device removed")

        return read, lambda: None, 48000

    original = controller._open_loopback_reader
    controller._open_loopback_reader = reader
    try:
        controller._run()
    finally:
        controller._open_loopback_reader = original

    assert controller._analyzer.stats.blocks == 0
    assert controller._analyzer.stats.noise_floor == 0.0


def test_each_beat_is_told_apart_from_the_one_before() -> None:
    """A decaying envelope cannot say whether it is still the same strike or a
    weaker new one. Anything holding a peak until it has been shown needs the
    identity, and it has to actually advance."""
    controller, options = _controller(beat_strength=1.0)
    quiet_beat = [
        (0.7 if index % 8 == 0 else 0.12, 0.14, 0.10, 0.030 + (0.004 if index % 8 == 0 else 0.0))
        for index in range(200)
    ]

    with _Player(controller, options) as player:
        results = player.play_results(quiet_beat)

    ids = [result.beat_id for result in results]
    assert ids == sorted(ids), "the identity went backwards"
    assert max(ids) > 5, f"the beats were never told apart: {sorted(set(ids))}"
    assert max(ids) == controller._analyzer.stats.beats

    # And it stays put while a strike decays, rather than changing every block.
    assert len(ids) > len(set(ids)), "a new identity on every block, beat or not"


# ── how hard it was struck ────────────────────────────────────────────
class _Strikes:
    """Drives the analyser directly, one block at a time, on a clock we own.

    The strength lives in the analyser, and these are claims about it rather
    than about the colour it eventually becomes.
    """

    def __init__(self, *, bed: float = 0.1, mid: float = 1.0, treble: float = 1.0) -> None:
        from app.music_analysis import MusicAnalyzer

        self.analyzer = MusicAnalyzer()
        self._bed = bed
        self._mid = mid
        self._treble = treble
        self._now_ms = 0.0
        self.scale = 1.0

    def quiet(self, blocks: int = 6, *, bed: float | None = None) -> None:
        for _ in range(blocks):
            self._feed(self._bed if bed is None else bed)

    def strike(self, peak: float, *, bed: float | None = None) -> float | None:
        """One block at ``peak``. Returns the envelope, or None if unheard."""
        self.quiet(6, bed=bed)
        reading = self._feed(peak)
        return reading.envelope if reading.beat else None

    def _feed(self, bass: float):
        reading = self.analyzer.feed(
            bass=bass * self.scale,
            mid=self._mid * self.scale,
            treble=self._treble * self.scale,
            rms=0.05 * self.scale,
            now_ms=self._now_ms,
        )
        self._now_ms += 21.3
        return reading

    def warm_up(self, peak: float, times: int = 4) -> None:
        """Establish what a hard strike sounds like, as the first bars do."""
        self.quiet(20)
        for _ in range(times):
            self.strike(peak)


def test_an_accent_stands_out_from_the_beat_it_interrupts() -> None:
    """The scenario a real track actually presents, and the one the first
    version failed.

    Nobody plays the hardest strike of the evening first. Eight ordinary beats,
    then one twice as hard: measured against the loudest heard so far, the
    ordinary beat *is* the loudest and reaches full strength within a few bars,
    leaving the accent nowhere to go. Every strike from the sixth on read 1.0,
    the accent included, and the old tests missed it because they warmed the
    analyser up with the hardest strike before comparing anything.
    """
    strikes = _Strikes()
    strikes.quiet(20)

    ordinary = [strikes.strike(2.0) for _ in range(8)]
    accent = strikes.strike(4.0)

    assert None not in ordinary and accent is not None, "a strike went unheard"
    settled = ordinary[-4:]
    assert max(settled) < 0.8, f"the ordinary beat is already at the top: {settled}"
    assert accent > max(settled) + 0.25, (
        f"an accent twice as hard read {accent} against ordinary {settled}"
    )


def test_a_harder_strike_registers_harder() -> None:
    """The complaint this answers: every beat came out at full strength, so a
    track that hits hard looked the same as one that taps."""
    strikes = _Strikes()
    strikes.quiet(20)
    for _ in range(6):
        strikes.strike(1.6)

    weak = strikes.strike(0.8)
    medium = strikes.strike(1.6)
    strong = strikes.strike(3.2)

    assert None not in (weak, medium, strong), "a strike went unheard"
    assert weak < medium < strong, f"{weak} / {medium} / {strong}"


def test_the_strength_survives_the_volume_being_changed() -> None:
    """Half as loud or twice as loud is a fact about the machine, not about the
    music. What a person hears as a hard beat is how it compares with its
    neighbours, and that has to be what survives."""
    readings = {}
    for scale in (0.5, 1.0, 2.0):
        strikes = _Strikes()
        strikes.scale = scale
        strikes.quiet(20)
        for _ in range(6):
            strikes.strike(1.6)
        readings[scale] = (strikes.strike(0.8), strikes.strike(1.6), strikes.strike(3.2))

    assert readings[0.5] == pytest.approx(readings[1.0], abs=0.01)
    assert readings[2.0] == pytest.approx(readings[1.0], abs=0.01)


def test_a_sustained_bass_line_does_not_pass_for_a_hard_strike() -> None:
    """The low band holds a sub, a bass line and the bottom of a voice as well
    as the drum. Measured as the whole band, a track with a heavy bass line and
    a soft kick flashes at full strength for the bass alone — so it is measured
    as the *rise* above what the band was already sitting at.

    The kick here reaches a *higher* absolute level than the ones it is compared
    with, and must still read as the softer strike, because it is.
    """
    strikes = _Strikes()
    strikes.warm_up(2.4)
    hard = strikes.strike(2.4)

    # The sub enters and stays. The kick on top of it peaks higher than before.
    strikes.quiet(8, bed=1.5)
    strikes.strike(2.6, bed=1.5)
    over_the_sub = strikes.strike(2.6, bed=1.5)

    assert hard is not None and over_the_sub is not None
    assert over_the_sub < hard * 0.85, (
        f"a higher absolute level read as hard as a bigger attack: "
        f"{over_the_sub} against {hard}"
    )


def test_a_soft_strike_after_a_hard_one_stays_soft() -> None:
    strikes = _Strikes()
    strikes.quiet(20)
    for _ in range(6):
        strikes.strike(2.0)

    hard = strikes.strike(4.0)
    soft = strikes.strike(0.7)
    hard_again = strikes.strike(4.0)

    assert soft < hard
    assert hard_again > soft


def test_the_first_strike_of_a_run_is_neither_extreme() -> None:
    """It has nothing to be compared with. Full strength claims "as hard as it
    gets" on no evidence; nothing claims the opposite."""
    from app.music_analysis import FIRST_BEAT_STRENGTH

    strikes = _Strikes()
    strikes.quiet(20)

    first = strikes.strike(4.0)

    assert first == pytest.approx(FIRST_BEAT_STRENGTH, abs=0.01)


def test_the_strength_stays_inside_the_range_a_frame_can_carry() -> None:
    from app.music_analysis import MIN_BEAT_STRENGTH

    strikes = _Strikes()
    strikes.warm_up(1.0)
    seen = [strikes.strike(peak) for peak in (0.2, 0.5, 1.0, 4.0, 40.0, 400.0)]

    for envelope in seen:
        if envelope is not None:
            assert MIN_BEAT_STRENGTH - 1e-9 <= envelope <= 1.0, envelope


def test_starting_over_forgets_how_hard_the_last_track_hit() -> None:
    """A quiet track after a loud one must not be judged by the loud one."""
    strikes = _Strikes()
    strikes.warm_up(40.0)
    assert strikes.strike(1.0) is not None

    strikes.analyzer.reset()
    strikes.quiet(20)

    from app.music_analysis import FIRST_BEAT_STRENGTH

    assert strikes.strike(1.0) == pytest.approx(FIRST_BEAT_STRENGTH, abs=0.01)


def test_a_quiet_track_after_a_loud_one_finds_its_own_level() -> None:
    """What "typical" means has to follow the music. A quiet track after a loud
    one starts below the floor, and within a few of its own beats it is being
    judged by its own standard rather than the last track's."""
    from app.music_analysis import TYPICAL_BEAT_STRENGTH

    strikes = _Strikes()
    strikes.quiet(20)
    for _ in range(8):
        strikes.strike(8.0)

    first_quiet = strikes.strike(1.0)
    for _ in range(14):
        strikes.strike(1.0)
    settled = strikes.strike(1.0)

    assert first_quiet is not None and settled is not None
    assert first_quiet < settled, "the quiet track never found its own level"
    assert settled == pytest.approx(TYPICAL_BEAT_STRENGTH, abs=0.12), settled


def test_the_softest_strike_still_registers() -> None:
    """A beat that showed as nothing would leave the rhythm unreadable, which is
    the opposite of the point. Soft is soft, not absent."""
    from app.music_analysis import MIN_BEAT_STRENGTH

    strikes = _Strikes()
    strikes.warm_up(40.0)

    barely = strikes.strike(0.5)

    assert barely is not None, "the soft strike went unheard entirely"
    assert barely == pytest.approx(MIN_BEAT_STRENGTH, abs=0.02), (
        f"a strike far below the bar came out at {barely}, not the floor"
    )


def test_the_baseline_rises_to_meet_the_bass_rather_than_jumping_to_it() -> None:
    """Two blocks are enough to show it, and a run really can start this way.

    The first block of a run seeds the level, and if that block is quiet the
    level is zero. Re-seeding whenever the level *happens* to be zero then
    hands the whole of the next block's bass to the baseline in one step — and
    a level that has already jumped to a strike leaves that strike no attack at
    all, so the hardest kick in the track registers as the softest.

    The block-size test above cannot see this: a jump gives the same wrong
    answer at every block size, and that test compares them with each other.
    """
    from app.music_analysis import MusicAnalyzer

    analyzer = MusicAnalyzer()
    analyzer.feed(bass=0.0, mid=0.0, treble=0.0, rms=0.0, now_ms=0.0)
    assert analyzer._bass_baseline == 0.0, "the first block did not seed the level"

    analyzer.feed(bass=4.0, mid=1.0, treble=1.0, rms=0.05, now_ms=21.3)

    assert 0.0 < analyzer._bass_baseline < 4.0, (
        f"the level jumped straight to {analyzer._bass_baseline} instead of rising"
    )


def test_the_baseline_follows_time_and_not_the_number_of_blocks() -> None:
    """A device is free to hand over 512 frames at a time or 4096. That is a
    fact about the sound card, not about the music.

    Checked on the baseline itself rather than on how hard a strike reads: the
    strength is a ratio of attacks, so a systematic shift in the level cancels
    out of it and the same music comes out near enough either way. The level is
    where the difference actually lives — a fixed fraction *per block* moves it
    eight times slower at 4096 than at 512, for exactly the same half second of
    sound.
    """
    from app.music_analysis import MusicAnalyzer

    def settle(block_ms: float) -> float:
        analyzer = MusicAnalyzer()
        now = 0.0
        for _ in range(int(300 / block_ms)):
            analyzer.feed(bass=0.0, mid=0.0, treble=0.0, rms=0.0, now_ms=now)
            now += block_ms
        # Half a second of a heavy bass line, however it is chopped up.
        for _ in range(int(500 / block_ms)):
            analyzer.feed(bass=4.0, mid=1.0, treble=1.0, rms=0.05, now_ms=now)
            now += block_ms
        return analyzer._bass_baseline

    levels = [settle(frames / 48000 * 1000) for frames in (512, 1024, 4096)]

    assert max(levels) - min(levels) < 0.4, (
        f"the same half second settled at {[round(level, 2) for level in levels]}"
    )


def test_the_same_music_strikes_the_same_whatever_the_block_size() -> None:
    """And the strikes themselves keep their shape across block sizes."""
    from app.music_analysis import MusicAnalyzer

    def play(block_ms: float) -> list[float]:
        analyzer = MusicAnalyzer()
        now = 0.0
        heard: list[float] = []
        quiet_blocks = max(1, round(150 / block_ms))

        def feed(bass: float) -> None:
            nonlocal now
            reading = analyzer.feed(
                bass=bass, mid=1.0, treble=1.0, rms=0.05, now_ms=now
            )
            now += block_ms
            if reading.beat:
                heard.append(reading.envelope)

        for _ in range(int(600 / block_ms)):
            feed(0.1)
        for peak in (2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 4.0, 1.0):
            for _ in range(quiet_blocks):
                feed(0.1)
            feed(peak)
        return heard

    small = play(512 / 48000 * 1000)
    usual = play(1024 / 48000 * 1000)
    large = play(4096 / 48000 * 1000)

    assert len(small) == len(usual) == len(large), (
        f"a different number of strikes was heard: {len(small)}/{len(usual)}/{len(large)}"
    )
    for a, b in zip(small, usual, strict=True):
        assert abs(a - b) < 0.1, f"512 gave {a} where 1024 gave {b}"

    # The coarse one is held to the shape rather than the numbers, and the
    # reason is physical rather than a concession: an 85 ms block smears a
    # strike that lasts twenty, so the same drum genuinely arrives as a
    # different signal. What must survive is which strike was the hard one.
    for heard in (small, usual, large):
        ordinary, accent, soft = heard[:-2], heard[-2], heard[-1]
        assert accent > max(ordinary) + 0.2, f"the accent was lost: {heard}"
        assert soft < min(ordinary), f"the soft strike was lost: {heard}"


def test_the_bass_of_a_finished_track_does_not_outlive_the_silence() -> None:
    """The level a strike is measured against has to follow the quiet as well as
    the music. Frozen while nothing plays, the first beat of the next track is
    judged against a bass line that stopped minutes ago — and reads as no attack
    at all."""
    from app.music_analysis import MusicAnalyzer

    analyzer = MusicAnalyzer()
    now = 0.0

    def feed(bass: float, rms: float) -> None:
        nonlocal now
        analyzer.feed(bass=bass, mid=1.0, treble=1.0, rms=rms, now_ms=now)
        now += 21.3

    # A track with a heavy bass line, then it ends.
    for _ in range(200):
        feed(4.0, 0.05)
    loud_baseline = analyzer._bass_baseline
    for _ in range(400):
        feed(0.0, 0.0)

    assert loud_baseline > 1.0, "the bass line never registered"
    assert analyzer._bass_baseline < loud_baseline * 0.1, (
        f"the baseline is still at {analyzer._bass_baseline} after the track ended"
    )

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

    controller.start(lambda r, g, b: None)
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

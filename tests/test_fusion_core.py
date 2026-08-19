"""What the compositor promises, checked on synthetic input.

The rules that matter are all about restraint: silence must return the frame to
the base *exactly*, a base that stopped arriving must send nothing rather than
something, and power must take away permission to write without taking away the
mode. Each of those is a specific number or a specific flag here, not an
impression.
"""

from __future__ import annotations

from app.fusion_core import (
    BASE_STALE_S,
    MAX_BEAT_GAIN,
    MAX_BEAT_RESERVE,
    MODULATION_FLOOR,
    BaseSample,
    ComposedFrame,
    FusionCompositor,
    MusicModulation,
    TransientOverlay,
)


class _Clock:
    """A monotonic clock a test can drive."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def _rig(*, mode: str = "screen_music") -> tuple[FusionCompositor, _Clock]:
    clock = _Clock()
    comp = FusionCompositor(clock=clock)
    comp.set_mode(mode)
    comp.set_sources_running(True)
    return comp, clock


def _feed(comp: FusionCompositor, clock: _Clock, *, level: float, beat: float = 0.0) -> None:
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.8, at=clock.now))
    comp.submit_music(MusicModulation(level=level, beat_envelope=beat, at=clock.now))


def _lit(frame) -> tuple[int, int, int]:
    """What the strip is actually told to show: the colour, dimmed and boosted.

    Every claim about how a beat looks has to be made here rather than on the
    factor alone. The factor is only half of it — the beat spends its reserve
    through the factor on a bright frame and amplifies the colour on a dark one,
    and a test that watched one of the two would call the other one broken.
    """
    scale = frame.brightness_factor * frame.beat_boost
    return tuple(min(255, round(channel * scale)) for channel in frame.rgb)


def _settle(
    comp: FusionCompositor, clock: _Clock, *, level: float, beat: float = 0.0, seconds: float = 3.0
) -> ComposedFrame:
    """Run a steady signal until the influence has stopped moving."""
    frame = ComposedFrame()
    steps = int(seconds / 0.05)
    for _ in range(steps):
        clock.advance(0.05)
        _feed(comp, clock, level=level, beat=beat)
        frame = comp.compose()
    return frame


# ── nothing to send is said out loud ──────────────────────────────────
def test_no_base_yet_sends_nothing_and_is_not_black() -> None:
    """Black is a colour someone may legitimately want. "I have nothing" has to
    be a separate answer or the two are indistinguishable at the caller."""
    comp, _clock = _rig()

    frame = comp.compose()

    assert frame.should_send is False
    assert frame.reason == "no_base"


def test_a_base_that_stopped_arriving_sends_nothing() -> None:
    """A frozen picture is worse than no picture: it looks exactly like a
    working one and it is wrong."""
    comp, clock = _rig()
    comp.submit_base(BaseSample(rgb=(10, 200, 90), at=clock.now))
    assert comp.compose().should_send is True

    clock.advance(BASE_STALE_S + 0.1)
    frame = comp.compose()

    assert frame.should_send is False
    assert frame.reason == "base_stale"
    assert frame.base_stale is True


# ── music moves brightness and nothing else ───────────────────────────
def test_silence_returns_the_frame_to_the_base_exactly() -> None:
    """Not approximately. If a fraction of the modulation survives silence then
    "the base" is not a state the strip can actually be in."""
    comp, clock = _rig()
    quiet = _settle(comp, clock, level=0.1)
    assert quiet.brightness_factor < 0.8, "the music was not being heard at all"

    # The music stops arriving; the base keeps coming.
    seen_between = False
    for _ in range(200):
        clock.advance(0.05)
        comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.8, at=clock.now))
        frame = comp.compose()
        if 0.0 < frame.brightness_factor - quiet.brightness_factor < 0.8 - quiet.brightness_factor:
            seen_between = True

    assert seen_between, "the modulation was cut rather than faded out"
    assert frame.activity == 0.0
    assert frame.brightness_factor == 0.8
    assert frame.music_stale is True
    assert frame.should_send is True


def test_music_never_changes_the_colour() -> None:
    """The screen says what colour, the music says how much of it."""
    comp, clock = _rig()

    loud = _settle(comp, clock, level=1.0, beat=1.0)
    quiet = _settle(comp, clock, level=0.05)

    assert loud.rgb == (200, 120, 40)
    assert quiet.rgb == (200, 120, 40)


def test_quiet_music_pulls_brightness_down_only_as_far_as_the_floor() -> None:
    """A strip that goes dark in every quiet passage reads as broken. The floor
    is a named constant precisely so this can be asserted against it."""
    comp, clock = _rig()

    frame = _settle(comp, clock, level=0.0)

    assert frame.brightness_factor == round(0.8 * MODULATION_FLOOR, 10) or abs(
        frame.brightness_factor - 0.8 * MODULATION_FLOOR
    ) < 0.01
    assert frame.brightness_factor > 0.0


def test_loud_music_takes_the_level_to_the_ceiling_and_stops_there() -> None:
    """Not to the top. What the beat spends has to already be free when the
    beat arrives, and at full volume there is nowhere else for it to come from.
    With the beat turned off the ceiling is the top, as it always was.
    """
    comp, clock = _rig()

    reserved = _settle(comp, clock, level=1.0)
    comp2, clock2 = _rig()
    for _ in range(60):
        clock2.advance(0.05)
        _feed(comp2, clock2, level=1.0)
        plain = comp2.compose(beat_gain=0.0)

    assert abs(reserved.brightness_factor - 0.8 * (1.0 - MAX_BEAT_RESERVE)) < 0.01
    assert abs(plain.brightness_factor - 0.8) < 0.01


def test_a_beat_is_an_impulse_above_where_the_music_already_was() -> None:
    comp, clock = _rig()
    steady = _settle(comp, clock, level=0.4)

    clock.advance(0.05)
    _feed(comp, clock, level=0.4, beat=1.0)
    beat = comp.compose(beat_gain=1.0)

    assert _lit(beat) > _lit(steady)
    assert beat.beat_boost <= MAX_BEAT_GAIN + 1e-9


def test_the_beat_slider_is_the_only_thing_aiming_the_impulse() -> None:
    comp, clock = _rig()
    _settle(comp, clock, level=0.4)

    clock.advance(0.05)
    _feed(comp, clock, level=0.4, beat=1.0)
    off = comp.compose(beat_gain=0.0)
    clock.advance(0.05)
    _feed(comp, clock, level=0.4, beat=1.0)
    full = comp.compose(beat_gain=1.0)

    assert _lit(full) > _lit(off)
    assert off.beat_boost == 1.0


# ── arriving and leaving smoothly ─────────────────────────────────────
def test_music_appearing_fades_in_rather_than_jumping() -> None:
    comp, clock = _rig()
    clock.advance(0.05)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.8, at=clock.now))
    comp.compose()

    clock.advance(0.05)
    _feed(comp, clock, level=0.0)
    first = comp.compose()

    assert 0.0 < first.activity < 0.5, "the influence arrived all at once"
    assert first.brightness_factor > 0.8 * MODULATION_FLOOR


def test_one_dropped_audio_block_is_not_silence() -> None:
    """Staleness is counted in real blocks. A gap of a single block on a fast
    device is normal jitter, and treating it as silence is a visible jump."""
    comp, clock = _rig()
    _settle(comp, clock, level=0.5)

    clock.advance(0.06)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.8, at=clock.now))
    frame = comp.compose()

    assert frame.music_stale is False


def test_a_slow_audio_device_is_not_permanently_stale() -> None:
    """A long block is a property of the device, not a sign that music stopped."""
    comp, clock = _rig()
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.8, at=clock.now))
    comp.submit_music(MusicModulation(level=0.5, at=clock.now, block_seconds=0.4))

    clock.advance(0.6)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.8, at=clock.now))

    assert comp.compose().music_stale is False


# ── power: permission to write, and nothing else ──────────────────────
def test_power_off_blocks_the_output_and_keeps_the_mode() -> None:
    """The change 0.4.0 makes on purpose. Today the mode is a running object and
    switching the strip off simply loses it."""
    comp, clock = _rig()
    _settle(comp, clock, level=0.5)

    comp.set_output_allowed(False)
    frame = comp.compose()

    assert frame.should_send is False
    assert frame.reason == "output_blocked"
    assert comp.mode == "screen_music", "the choice was forgotten"
    assert comp.sources_running is True


def test_power_on_waits_for_a_fresh_frame_instead_of_replaying_the_old_one() -> None:
    """What was captured before the strip went off describes a screen from
    minutes ago, and it would be shown at the exact moment someone looks."""
    comp, clock = _rig()
    _settle(comp, clock, level=0.5)
    comp.set_output_allowed(False)

    clock.advance(120.0)
    comp.set_output_allowed(True)
    frame = comp.compose()

    assert frame.should_send is False
    assert frame.reason == "no_base"

    clock.advance(0.05)
    _feed(comp, clock, level=0.5)
    assert comp.compose().should_send is True


def test_power_off_does_not_leave_the_music_influence_wound_up() -> None:
    """Coming back at full modulation from a beat that happened before the strip
    was switched off would be a flash at the wrong moment."""
    comp, clock = _rig()
    _settle(comp, clock, level=0.2)
    comp.set_output_allowed(False)
    comp.set_output_allowed(True)

    clock.advance(0.05)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.8, at=clock.now))
    frame = comp.compose()

    assert frame.activity == 0.0
    assert frame.brightness_factor == 0.8


# ── the overlay ───────────────────────────────────────────────────────
def test_an_overlay_takes_the_frame_and_gives_it_back_exactly() -> None:
    comp, clock = _rig()
    # Settled first: "gives it back" means back to what the music was already
    # doing, and comparing against a frame taken before the music wound in
    # would be measuring the fade-in rather than the overlay.
    before = _settle(comp, clock, level=1.0)

    comp.show_overlay(
        TransientOverlay(rgb=(255, 0, 0), brightness_factor=1.0, started_at=clock.now, duration=1.0)
    )
    clock.advance(0.5)
    _feed(comp, clock, level=1.0)
    during = comp.compose()

    clock.advance(0.6)
    _feed(comp, clock, level=1.0)
    after = comp.compose()

    assert during.rgb == (255, 0, 0)
    assert during.overlay is True
    assert after.rgb == before.rgb
    assert after.overlay is False
    assert abs(after.brightness_factor - before.brightness_factor) < 0.02


def test_an_overlay_fades_in_and_out_rather_than_cutting() -> None:
    comp, clock = _rig()
    _feed(comp, clock, level=0.0)
    comp.show_overlay(
        TransientOverlay(
            rgb=(0, 0, 255), started_at=clock.now, duration=1.0, fade_in=0.2, fade_out=0.2
        )
    )

    clock.advance(0.1)
    _feed(comp, clock, level=0.0)
    rising = comp.compose()
    clock.advance(0.4)
    _feed(comp, clock, level=0.0)
    full = comp.compose()

    assert 0 < rising.rgb[2] < full.rgb[2]


def test_the_screen_keeps_arriving_underneath_an_overlay() -> None:
    """An overlay covers the frame, it does not pause the world. What appears
    when it ends has to be the screen as it is *now* — a second of the picture
    from before the alert would be a visible rewind."""
    comp, clock = _rig(mode="screen")
    comp.submit_base(BaseSample(rgb=(10, 20, 30), brightness_factor=0.5, at=clock.now))
    comp.compose()

    comp.show_overlay(
        TransientOverlay(rgb=(255, 0, 0), started_at=clock.now, duration=0.5, fade_out=0.0)
    )
    # The screen moves on while the alert is up.
    for _ in range(10):
        clock.advance(0.05)
        comp.submit_base(BaseSample(rgb=(90, 180, 240), brightness_factor=0.5, at=clock.now))
        comp.compose()

    clock.advance(0.05)
    comp.submit_base(BaseSample(rgb=(90, 180, 240), brightness_factor=0.5, at=clock.now))
    frame = comp.compose()

    assert frame.overlay is False
    assert frame.rgb == (90, 180, 240), "the picture from before the overlay came back"


def test_an_overlay_is_not_shown_over_a_screen_that_has_stopped() -> None:
    """Deliberate, and worth stating: an overlay is composed *onto* a base. With
    no fresh base there is nothing to return to when it ends, and lighting the
    strip would claim the capture is alive when it is not."""
    comp, clock = _rig(mode="screen")
    comp.submit_base(BaseSample(rgb=(10, 20, 30), at=clock.now))

    clock.advance(BASE_STALE_S + 0.1)
    comp.show_overlay(TransientOverlay(rgb=(255, 0, 0), started_at=clock.now, duration=1.0))
    frame = comp.compose()

    assert frame.should_send is False
    assert frame.reason == "base_stale"


def test_an_overlay_with_no_fade_still_ends_when_its_time_is_up() -> None:
    """A hard-edged overlay is a legitimate thing to ask for, and it is the one
    shape where "past the end" is not covered by the fade arithmetic. Without an
    explicit end it would simply stay on the strip for good."""
    comp, clock = _rig()
    _feed(comp, clock, level=0.0)
    comp.show_overlay(
        TransientOverlay(
            rgb=(255, 0, 0), started_at=clock.now, duration=0.3, fade_in=0.0, fade_out=0.0
        )
    )

    clock.advance(0.5)
    _feed(comp, clock, level=0.0)
    frame = comp.compose()

    assert frame.overlay is False
    assert frame.rgb == (200, 120, 40)


def test_an_overlay_blends_its_brightness_in_rather_than_replacing_it() -> None:
    """Halfway through a fade the frame is halfway between the two, brightness_factor
    included. Snapping brightness_factor while the colour eases is the flicker a fade
    exists to avoid."""
    comp, clock = _rig()
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.2, at=clock.now))
    comp.show_overlay(
        TransientOverlay(
            rgb=(255, 0, 0), brightness_factor=1.0, started_at=clock.now, duration=2.0, fade_in=0.4
        )
    )

    clock.advance(0.2)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness_factor=0.2, at=clock.now))
    frame = comp.compose()

    assert 0.2 < frame.brightness_factor < 1.0
    assert abs(frame.brightness_factor - 0.6) < 0.05


def test_an_expired_overlay_is_forgotten_and_does_not_come_back() -> None:
    comp, clock = _rig()
    _feed(comp, clock, level=0.0)
    comp.show_overlay(TransientOverlay(rgb=(255, 0, 0), started_at=clock.now, duration=0.2))

    clock.advance(1.0)
    _feed(comp, clock, level=0.0)
    comp.compose()
    clock.advance(0.05)
    _feed(comp, clock, level=0.0)

    assert comp.compose().overlay is False


def test_an_overlay_is_not_sent_while_the_strip_is_off() -> None:
    """Permission to write outranks everything, including something urgent."""
    comp, clock = _rig()
    _feed(comp, clock, level=0.0)
    comp.set_output_allowed(False)
    comp.show_overlay(TransientOverlay(rgb=(255, 0, 0), started_at=clock.now, duration=1.0))

    assert comp.compose().should_send is False


# ── the plain mode still goes through here ────────────────────────────
def test_screen_only_is_the_same_path_with_no_music() -> None:
    """There is no second, older way to reach the strip. Screen Sync on its own
    is this compositor with nothing modulating it."""
    comp, clock = _rig(mode="screen")
    clock.advance(0.05)
    comp.submit_base(BaseSample(rgb=(12, 34, 56), brightness_factor=0.5, at=clock.now))

    frame = comp.compose()

    assert frame.should_send is True
    assert frame.rgb == (12, 34, 56)
    assert frame.brightness_factor == 0.5
    assert frame.music_stale is True
    assert frame.base_source == "screen"


def test_choosing_another_mode_drops_what_the_old_one_left_behind() -> None:
    comp, clock = _rig()
    _settle(comp, clock, level=0.5)

    comp.set_mode("screen")

    assert comp.compose().reason == "no_base"


def test_the_factor_never_leaves_the_range_a_colour_can_be_scaled_by() -> None:
    comp, clock = _rig()
    comp.submit_base(BaseSample(rgb=(255, 255, 255), brightness_factor=1.0, at=clock.now))
    _settle(comp, clock, level=1.0, beat=1.0)

    clock.advance(0.05)
    _feed(comp, clock, level=1.0, beat=1.0)
    frame = comp.compose(beat_gain=1.0)

    assert 0.0 <= frame.brightness_factor <= 1.0


def test_the_first_frame_after_a_long_pause_still_fades_in() -> None:
    """Forgetting the inputs has to forget the clock reading with them.

    Between a stop and the next start, minutes of wall time pass. Kept, that gap
    becomes the elapsed time of the first frame, the smoothing step reaches 1.0,
    and the very first audio block lands at full influence — a jump into a
    dimmed strip at the moment the mode comes back.
    """
    comp, clock = _rig()
    _settle(comp, clock, level=0.5)
    assert comp.compose().activity > 0.9

    comp.forget_inputs()
    clock.advance(300.0)

    clock.advance(0.05)
    _feed(comp, clock, level=0.5)
    first = comp.compose()

    assert first.activity == 0.0, "five minutes of pause counted as elapsed time"
    assert first.brightness_factor == 0.8, "the base was not what came back"

    clock.advance(0.05)
    _feed(comp, clock, level=0.5)
    assert 0.0 < comp.compose().activity < 0.5, "the influence did not resume gradually"


# ── the beat has to be visible against a picture that moves ───────────
def _play(rgb, *, level: float, gain: float, beat: float = 0.0):
    """Settle on one colour and one volume, then strike one beat."""
    clock = _Clock()
    comp = FusionCompositor(clock=clock)
    comp.set_mode("screen_music")
    comp.set_sources_running(True)
    steady = ComposedFrame()
    for _ in range(80):
        clock.advance(0.05)
        comp.submit_base(BaseSample(rgb=rgb, at=clock.now))
        comp.submit_music(MusicModulation(level=level, at=clock.now))
        steady = comp.compose(beat_gain=gain)
    clock.advance(0.05)
    comp.submit_base(BaseSample(rgb=rgb, at=clock.now))
    comp.submit_music(MusicModulation(level=level, beat_envelope=beat, at=clock.now))
    return steady, comp.compose(beat_gain=gain)


def _ratios(colour) -> tuple[float, float]:
    top = max(colour) or 1
    return (colour[1] / top, colour[2] / top)


def test_a_beat_lands_on_a_bright_frame_at_full_volume() -> None:
    """The case that was measurably zero. At full volume the level was already
    at the ceiling and the impulse was clipped away entirely — a music video is
    exactly that, continuously, which is why the beat could not be seen."""
    steady, beat = _play((255, 255, 255), level=1.0, gain=1.0, beat=1.0)

    assert max(_lit(steady)) < 255, "no reserve was kept for the beat"
    assert max(_lit(beat)) - max(_lit(steady)) >= 30, (
        f"the beat is still invisible: {_lit(steady)} -> {_lit(beat)}"
    )


def test_a_beat_amplifies_a_dark_frame_rather_than_only_uncovering_it() -> None:
    """On a dark picture the reserve buys almost nothing: returning to full
    restores the same dark colour. The colour itself has to grow."""
    steady, beat = _play((60, 30, 15), level=1.0, gain=1.0, beat=1.0)

    lit_steady, lit_beat = _lit(steady), _lit(beat)
    assert beat.beat_boost > 1.2, "the dark frame was never amplified"
    assert max(lit_beat) > max(lit_steady) * 1.25, f"{lit_steady} -> {lit_beat}"


def test_a_beat_on_a_saturated_frame_keeps_the_hue() -> None:
    """The frame where a naive gain breaks: red reaches 255 first and the other
    channels keep climbing, sliding the colour toward yellow. Ratios are
    compared with a byte of rounding, which is all the strip can express."""
    steady, beat = _play((250, 120, 30), level=1.0, gain=1.0, beat=1.0)

    lit_steady, lit_beat = _lit(steady), _lit(beat)
    before, after = _ratios(lit_steady), _ratios(lit_beat)
    assert max(lit_beat) > max(lit_steady), "the beat did nothing"
    for index in range(2):
        # One byte at the top of the range is the finest difference there is.
        assert abs(before[index] - after[index]) <= 1.0 / max(lit_beat), (
            f"the hue moved: {lit_steady} -> {lit_beat}"
        )


def test_no_channel_is_ever_pushed_past_what_the_strip_takes() -> None:
    for colour in ((255, 255, 255), (250, 120, 30), (255, 10, 0), (60, 30, 15)):
        for level in (0.0, 0.5, 1.0):
            _steady, beat = _play(colour, level=level, gain=1.0, beat=1.0)
            assert max(_lit(beat)) <= 255, colour


def test_the_reserve_appears_gradually_and_not_at_the_first_percent() -> None:
    """A slider is dragged through its whole range. Switching the reserve on
    above zero would darken every loud passage by a fifth in one step, for a
    nudge from 0% to 1%."""
    levels = []
    for gain in (0.0, 0.01, 0.05, 0.2, 0.5, 1.0):
        steady, _beat = _play((255, 255, 255), level=1.0, gain=gain)
        levels.append(max(_lit(steady)))

    assert levels[0] == 255, "the reserve costs brightness with the beat turned off"
    assert levels[0] - levels[1] <= 3, f"a cliff at the first percent: {levels}"
    assert levels == sorted(levels, reverse=True), f"not monotonic: {levels}"
    assert levels[-1] == round(255 * (1.0 - MAX_BEAT_RESERVE)), levels


def test_with_the_beat_at_zero_the_ordinary_modulation_is_untouched() -> None:
    """The slider aims the impulse, not the whole mode. Turning it down must
    leave music still moving the level, or it quietly becomes a master control
    for Fusion."""
    quiet, _ = _play((255, 255, 255), level=0.0, gain=0.0)
    loud, beat = _play((255, 255, 255), level=1.0, gain=0.0, beat=1.0)

    assert max(_lit(quiet)) < max(_lit(loud)), "music stopped moving the level"
    assert max(_lit(loud)) == 255, "a reserve was kept with the beat switched off"
    assert beat.beat_boost == 1.0
    assert _lit(beat) == _lit(loud), "an impulse landed with the beat switched off"


def test_silence_gives_back_the_screen_frame_byte_for_byte() -> None:
    """Whatever the slider says. After the music fades out the strip shows the
    picture, not the picture minus a reserve."""
    clock = _Clock()
    comp = FusionCompositor(clock=clock)
    comp.set_mode("screen_music")
    comp.set_sources_running(True)
    for _ in range(80):
        clock.advance(0.05)
        comp.submit_base(BaseSample(rgb=(200, 120, 40), at=clock.now))
        comp.submit_music(MusicModulation(level=1.0, beat_envelope=1.0, at=clock.now))
        comp.compose(beat_gain=1.0)

    for _ in range(200):
        clock.advance(0.05)
        comp.submit_base(BaseSample(rgb=(200, 120, 40), at=clock.now))
        frame = comp.compose(beat_gain=1.0)

    assert frame.activity == 0.0
    assert frame.beat_boost == 1.0
    assert _lit(frame) == (200, 120, 40)


def test_the_plain_screen_mode_is_the_screen_byte_for_byte() -> None:
    comp, clock = _rig(mode="screen")
    clock.advance(0.05)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), at=clock.now))

    frame = comp.compose(beat_gain=1.0)

    assert frame.beat_boost == 1.0
    assert _lit(frame) == (200, 120, 40)

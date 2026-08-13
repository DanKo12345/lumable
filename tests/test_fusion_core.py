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
    BEAT_HEADROOM,
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
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.8, at=clock.now))
    comp.submit_music(MusicModulation(level=level, beat_envelope=beat, at=clock.now))


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
    assert quiet.brightness < 0.8, "the music was not being heard at all"

    # The music stops arriving; the base keeps coming.
    seen_between = False
    for _ in range(200):
        clock.advance(0.05)
        comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.8, at=clock.now))
        frame = comp.compose()
        if 0.0 < frame.brightness - quiet.brightness < 0.8 - quiet.brightness:
            seen_between = True

    assert seen_between, "the modulation was cut rather than faded out"
    assert frame.activity == 0.0
    assert frame.brightness == 0.8
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

    assert frame.brightness == round(0.8 * MODULATION_FLOOR, 10) or abs(
        frame.brightness - 0.8 * MODULATION_FLOOR
    ) < 0.01
    assert frame.brightness > 0.0


def test_loud_music_leaves_the_base_brightness_alone() -> None:
    comp, clock = _rig()

    frame = _settle(comp, clock, level=1.0)

    assert abs(frame.brightness - 0.8) < 0.01


def test_a_beat_is_an_impulse_above_where_the_music_already_was() -> None:
    comp, clock = _rig()
    steady = _settle(comp, clock, level=0.4)

    clock.advance(0.05)
    _feed(comp, clock, level=0.4, beat=1.0)
    beat = comp.compose(beat_gain=1.0)

    assert beat.brightness > steady.brightness
    assert beat.brightness <= steady.brightness + BEAT_HEADROOM + 0.01


def test_the_beat_slider_is_the_only_thing_aiming_the_impulse() -> None:
    comp, clock = _rig()
    _settle(comp, clock, level=0.4)

    clock.advance(0.05)
    _feed(comp, clock, level=0.4, beat=1.0)
    off = comp.compose(beat_gain=0.0)
    clock.advance(0.05)
    _feed(comp, clock, level=0.4, beat=1.0)
    full = comp.compose(beat_gain=1.0)

    assert full.brightness > off.brightness


# ── arriving and leaving smoothly ─────────────────────────────────────
def test_music_appearing_fades_in_rather_than_jumping() -> None:
    comp, clock = _rig()
    clock.advance(0.05)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.8, at=clock.now))
    comp.compose()

    clock.advance(0.05)
    _feed(comp, clock, level=0.0)
    first = comp.compose()

    assert 0.0 < first.activity < 0.5, "the influence arrived all at once"
    assert first.brightness > 0.8 * MODULATION_FLOOR


def test_one_dropped_audio_block_is_not_silence() -> None:
    """Staleness is counted in real blocks. A gap of a single block on a fast
    device is normal jitter, and treating it as silence is a visible jump."""
    comp, clock = _rig()
    _settle(comp, clock, level=0.5)

    clock.advance(0.06)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.8, at=clock.now))
    frame = comp.compose()

    assert frame.music_stale is False


def test_a_slow_audio_device_is_not_permanently_stale() -> None:
    """A long block is a property of the device, not a sign that music stopped."""
    comp, clock = _rig()
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.8, at=clock.now))
    comp.submit_music(MusicModulation(level=0.5, at=clock.now, block_seconds=0.4))

    clock.advance(0.6)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.8, at=clock.now))

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
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.8, at=clock.now))
    frame = comp.compose()

    assert frame.activity == 0.0
    assert frame.brightness == 0.8


# ── the overlay ───────────────────────────────────────────────────────
def test_an_overlay_takes_the_frame_and_gives_it_back_exactly() -> None:
    comp, clock = _rig()
    clock.advance(0.05)
    _feed(comp, clock, level=1.0)
    before = comp.compose()

    comp.show_overlay(
        TransientOverlay(rgb=(255, 0, 0), brightness=1.0, started_at=clock.now, duration=1.0)
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
    assert abs(after.brightness - before.brightness) < 0.02


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
    """Halfway through a fade the frame is halfway between the two, brightness
    included. Snapping brightness while the colour eases is the flicker a fade
    exists to avoid."""
    comp, clock = _rig()
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.2, at=clock.now))
    comp.show_overlay(
        TransientOverlay(
            rgb=(255, 0, 0), brightness=1.0, started_at=clock.now, duration=2.0, fade_in=0.4
        )
    )

    clock.advance(0.2)
    comp.submit_base(BaseSample(rgb=(200, 120, 40), brightness=0.2, at=clock.now))
    frame = comp.compose()

    assert 0.2 < frame.brightness < 1.0
    assert abs(frame.brightness - 0.6) < 0.05


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
    comp.submit_base(BaseSample(rgb=(12, 34, 56), brightness=0.5, at=clock.now))

    frame = comp.compose()

    assert frame.should_send is True
    assert frame.rgb == (12, 34, 56)
    assert frame.brightness == 0.5
    assert frame.music_stale is True
    assert frame.base_source == "screen"


def test_choosing_another_mode_drops_what_the_old_one_left_behind() -> None:
    comp, clock = _rig()
    _settle(comp, clock, level=0.5)

    comp.set_mode("screen")

    assert comp.compose().reason == "no_base"


def test_brightness_never_leaves_the_range_the_drivers_accept() -> None:
    comp, clock = _rig()
    comp.submit_base(BaseSample(rgb=(255, 255, 255), brightness=1.0, at=clock.now))
    _settle(comp, clock, level=1.0, beat=1.0)

    clock.advance(0.05)
    _feed(comp, clock, level=1.0, beat=1.0)
    frame = comp.compose(beat_gain=1.0)

    assert 0.0 <= frame.brightness <= 1.0
    assert 0 <= frame.brightness8 <= 255

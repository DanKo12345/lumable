from __future__ import annotations

from app.diy_effects import (
    DiyEffect,
    DiyStep,
    color_at,
    duration_scale,
    frames,
    total_duration_ms,
)

RED = (255, 0, 0)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)


def _two_step_fade() -> DiyEffect:
    # red held 100ms, then fade to blue over 100ms and hold 100ms.
    return DiyEffect(
        steps=(
            DiyStep(RED, transition_ms=0, hold_ms=100),
            DiyStep(BLUE, transition_ms=100, hold_ms=100),
        ),
        speed=50,
    )


def test_total_duration() -> None:
    assert total_duration_ms(_two_step_fade()) == 300


def test_hold_returns_step_colour() -> None:
    effect = _two_step_fade()
    assert color_at(effect, 0) == RED       # start of red hold
    assert color_at(effect, 50) == RED      # mid red hold
    assert color_at(effect, 250) == BLUE    # inside blue hold


def test_fade_midpoint_is_between_colours() -> None:
    effect = _two_step_fade()
    # blue step transition runs t in [100,200): midpoint at t=150 → halfway red→blue
    mid = color_at(effect, 150)
    assert mid == (128, 0, 128)


def test_loops() -> None:
    effect = _two_step_fade()
    total = total_duration_ms(effect)
    for t in (0, 37, 150, 299):
        assert color_at(effect, t) == color_at(effect, t + total)


def test_cut_transition_is_instant() -> None:
    effect = DiyEffect(
        steps=(
            DiyStep(RED, transition_ms=0, hold_ms=100),
            DiyStep(GREEN, transition_ms=0, hold_ms=100),
        ),
        speed=50,
    )
    assert color_at(effect, 100) == GREEN  # first instant of the green segment


def test_first_step_fades_from_last_on_loop() -> None:
    # First step has a transition, so it should fade in from the last step's colour.
    effect = DiyEffect(
        steps=(
            DiyStep(BLUE, transition_ms=100, hold_ms=0),
            DiyStep(RED, transition_ms=0, hold_ms=100),
        ),
        speed=50,
    )
    # at t=50, halfway through blue's fade-in from red (the last colour)
    assert color_at(effect, 50) == (128, 0, 128)


def test_duration_scale_monotonic() -> None:
    assert duration_scale(0) > duration_scale(50) > duration_scale(100)
    assert duration_scale(100) < 1.0 < duration_scale(0)


def test_frames_nonempty_and_sane() -> None:
    result = frames(_two_step_fade(), interval_ms=50)
    assert len(result) >= 2
    assert all(0 <= c <= 255 for frame in result for c in frame)


def test_motion_none_leaves_colour_steady() -> None:
    # Default motion is "none": colour is identical across the whole hold.
    effect = DiyEffect(steps=(DiyStep(RED, 0, 1500), DiyStep(BLUE, 0, 100)))
    assert color_at(effect, 0) == RED
    assert color_at(effect, 700) == RED


def test_breathe_motion_dims_then_peaks() -> None:
    effect = DiyEffect(
        steps=(DiyStep(RED, 0, 1500, motion="breathe"), DiyStep(BLUE, 0, 100)),
    )
    dim = color_at(effect, 0)       # start of step -> breathe trough
    peak = color_at(effect, 750)    # half a 1500ms motion cycle -> peak
    assert dim[0] < peak[0]
    assert peak == RED              # peak returns the base colour unchanged
    assert all(0 <= c <= 255 for c in dim)


def test_strobe_motion_blinks_off() -> None:
    effect = DiyEffect(
        steps=(DiyStep(GREEN, 0, 1500, motion="strobe"), DiyStep(BLUE, 0, 100)),
    )
    levels = [max(color_at(effect, t)) for t in range(0, 1500, 20)]
    assert min(levels) <= 30       # blinks nearly off part of the cycle
    assert max(levels) >= 200      # and fully on the rest


def test_unknown_motion_is_safe() -> None:
    effect = DiyEffect(steps=(DiyStep(RED, 0, 100, motion="bogus"), DiyStep(BLUE, 0, 100)))
    assert color_at(effect, 0) == RED


def test_empty_effect_is_safe() -> None:
    assert color_at(DiyEffect(steps=()), 0) == (0, 0, 0)
    assert frames(DiyEffect(steps=()), 50) == [(0, 0, 0)]

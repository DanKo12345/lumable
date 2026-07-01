from __future__ import annotations

from dataclasses import dataclass

from app.color_fade import lerp_rgb

RGB = tuple[int, int, int]

# A user-built ("DIY") effect is a looping timeline of colour steps. Each step
# fades in from the previous colour over ``transition_ms`` (0 = instant cut),
# then holds its colour for ``hold_ms``. After the last step it loops back to the
# first (the first step's transition fades from the last step's colour). It's all
# pure maths here so it can stream to any controller via the colour-stream engine.

MIN_STEPS = 2
MAX_STEPS = 8
MIN_MS = 0
MAX_MS = 10_000


@dataclass(frozen=True)
class DiyStep:
    rgb: RGB
    transition_ms: int  # fade-in time from the previous step's colour
    hold_ms: int        # time held at this step's colour


@dataclass(frozen=True)
class DiyEffect:
    steps: tuple[DiyStep, ...]
    speed: int = 50  # 0 = slowest, 100 = fastest (scales every duration)


def total_duration_ms(effect: DiyEffect) -> int:
    return sum(step.transition_ms + step.hold_ms for step in effect.steps)


def color_at(effect: DiyEffect, t_ms: float) -> RGB:
    """Colour of the looping animation at time ``t_ms`` (raw, speed not applied)."""
    steps = effect.steps
    if not steps:
        return (0, 0, 0)
    total = total_duration_ms(effect)
    if total <= 0:
        return steps[0].rgb
    t = t_ms % total
    prev = steps[-1].rgb  # loop: first step fades in from the last colour
    for step in steps:
        if t < step.transition_ms:
            frac = t / step.transition_ms if step.transition_ms > 0 else 1.0
            return lerp_rgb(prev, step.rgb, frac)
        t -= step.transition_ms
        if t < step.hold_ms:
            return step.rgb
        t -= step.hold_ms
        prev = step.rgb
    return steps[-1].rgb


def duration_scale(speed: int) -> float:
    """Multiplier applied to every duration: higher speed → shorter (faster).

    speed 0 → 2.0× (slow), 50 → ~1.2×, 100 → 0.4× (fast).
    """
    speed = max(0, min(100, int(speed)))
    return 2.0 - (speed / 100.0) * 1.6


def frames(effect: DiyEffect, interval_ms: int) -> list[RGB]:
    """One loop sampled at ``interval_ms`` (speed applied). Handy for preview and
    for feeding a fixed-rate stream. Always returns at least one frame."""
    interval_ms = max(1, int(interval_ms))
    scaled_total = total_duration_ms(effect) * duration_scale(effect.speed)
    if scaled_total <= 0:
        return [color_at(effect, 0.0)]
    out: list[RGB] = []
    elapsed = 0.0
    while elapsed < scaled_total:
        # Convert the (speed-scaled) wall-clock position back to raw timeline.
        raw = elapsed / duration_scale(effect.speed)
        out.append(color_at(effect, raw))
        elapsed += interval_ms
    return out or [color_at(effect, 0.0)]

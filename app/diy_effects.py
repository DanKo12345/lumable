from __future__ import annotations

import math
from dataclasses import dataclass

from app import software_effects as sfx
from app.color_fade import lerp_rgb

RGB = tuple[int, int, int]

# A user-built ("DIY") effect is a looping timeline of colour steps. Each step
# fades in from the previous colour over ``transition_ms`` (0 = instant cut),
# then holds its colour for ``hold_ms``. After the last step it loops back to the
# first (the first step's transition fades from the last step's colour). It's all
# pure maths here so it can stream to any controller via the colour-stream engine.

MIN_STEPS = 2
MAX_STEPS = 12
MIN_MS = 0
MAX_MS = 10_000

# Each step may carry a per-step "motion" that modulates its colour's brightness
# while it's on-screen (during its whole transition + hold span), reusing the
# software-effect generators. "none" leaves the colour steady. One motion cycle
# spans MOTION_PERIOD_MS so the liveliness reads the same regardless of step length.
MOTION_KEYS: tuple[str, ...] = (
    "none",
    "breathe",
    "pulse",
    "twinkle",
    "flicker",
    "fade_in",
    "fade_out",
    "strobe",
)
MOTION_PERIOD_MS = 1500
_MOTION_FUNCS = {
    "breathe": sfx.breathing,
    "pulse": sfx.heartbeat,
    "twinkle": sfx.twinkle,
    "strobe": sfx.strobe,
}


@dataclass(frozen=True)
class DiyStep:
    rgb: RGB
    transition_ms: int      # fade-in time from the previous step's colour
    hold_ms: int            # time held at this step's colour
    motion: str = "none"    # per-step brightness motion (see MOTION_KEYS)


@dataclass(frozen=True)
class DiyEffect:
    steps: tuple[DiyStep, ...]
    speed: int = 50  # 0 = slowest, 100 = fastest (scales every duration)


def total_duration_ms(effect: DiyEffect) -> int:
    return sum(step.transition_ms + step.hold_ms for step in effect.steps)


def timeline_stops(effect: DiyEffect) -> tuple[tuple[float, RGB], ...]:
    """Gradient stops that describe the real, duration-weighted DIY timeline."""
    total = total_duration_ms(effect)
    if not effect.steps:
        return ((0.0, (40, 40, 44)), (1.0, (40, 40, 44)))
    if total <= 0:
        color = effect.steps[0].rgb
        return ((0.0, color), (1.0, color))

    stops: list[tuple[float, RGB]] = []
    cursor = 0
    previous = effect.steps[-1].rgb
    for step in effect.steps:
        start = cursor / total
        if step.transition_ms > 0:
            stops.append((start, previous))
            cursor += step.transition_ms
            stops.append((cursor / total, step.rgb))
        else:
            # The preceding hold already ends at this same position. Two colours
            # at one stop make the preview show the same hard cut as playback.
            stops.append((start, step.rgb))
        cursor += step.hold_ms
        stops.append((cursor / total, step.rgb))
        previous = step.rgb
    return tuple(stops)


def timeline_boundaries(effect: DiyEffect) -> tuple[float, ...]:
    """End position of every step except the last, in the 0..1 timeline."""
    total = total_duration_ms(effect)
    if total <= 0:
        return ()
    cursor = 0
    boundaries: list[float] = []
    for step in effect.steps[:-1]:
        cursor += step.transition_ms + step.hold_ms
        boundaries.append(cursor / total)
    return tuple(boundaries)


def _scale(rgb: RGB, level: float) -> RGB:
    return (
        max(0, min(255, round(rgb[0] * level))),
        max(0, min(255, round(rgb[1] * level))),
        max(0, min(255, round(rgb[2] * level))),
    )


def _apply_motion(motion: str, rgb: RGB, t_in_step_ms: float, span_ms: float) -> RGB:
    """Modulate ``rgb`` by the step's motion at ``t_in_step_ms`` into the step."""
    progress = max(0.0, min(1.0, t_in_step_ms / span_ms)) if span_ms > 0 else 1.0
    if motion == "fade_in":
        return _scale(rgb, 0.08 + 0.92 * progress)
    if motion == "fade_out":
        return _scale(rgb, 1.0 - 0.92 * progress)
    if motion == "flicker":
        phase = (t_in_step_ms % MOTION_PERIOD_MS) / MOTION_PERIOD_MS
        level = 0.58 + 0.22 * math.sin(phase * math.tau * 2.7 + 1.3) + 0.14 * math.sin(
            phase * math.tau * 6.1 + 0.7
        )
        return _scale(rgb, max(0.22, min(1.0, level)))
    func = _MOTION_FUNCS.get(motion)
    if func is None:
        return rgb
    phase = (t_in_step_ms % MOTION_PERIOD_MS) / MOTION_PERIOD_MS
    return func(phase, rgb)


def color_at(effect: DiyEffect, t_ms: float) -> RGB:
    """Colour of the looping animation at time ``t_ms`` (raw, speed not applied)."""
    steps = effect.steps
    if not steps:
        return (0, 0, 0)
    total = total_duration_ms(effect)
    if total <= 0:
        return _apply_motion(steps[0].motion, steps[0].rgb, 0.0, 0.0)
    t = t_ms % total
    prev = steps[-1].rgb  # loop: first step fades in from the last colour
    for step in steps:
        span = step.transition_ms + step.hold_ms
        if t < span:
            if t < step.transition_ms:
                frac = t / step.transition_ms if step.transition_ms > 0 else 1.0
                base = lerp_rgb(prev, step.rgb, frac)
            else:
                base = step.rgb
            return _apply_motion(step.motion, base, t, span)
        t -= span
        prev = step.rgb
    return _apply_motion(steps[-1].motion, steps[-1].rgb, 0.0, 0.0)


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

from __future__ import annotations

import math

RGB = tuple[int, int, int]

# App-driven animations stream their colour through ColorStreamEngine, so they
# work on any controller regardless of which effects its firmware supports.
# "rainbow" is intentionally omitted from the picker: controllers' firmware
# already does a smooth rainbow on-device (and better). The app effects focus on
# what firmware can't do (breathe the current colour, candle flicker, gradients).
# render() still supports "rainbow" for any controller that lacks it in firmware.
EFFECT_KEYS: tuple[str, ...] = ("breathing", "heartbeat", "candle", "storm", "gradient", "lava", "aurora")

_GRADIENT_PALETTE: tuple[RGB, RGB, RGB] = ((255, 80, 70), (180, 90, 255), (60, 190, 255))
_LAVA_PALETTE: tuple[RGB, ...] = ((190, 20, 10), (255, 95, 0), (210, 30, 120), (120, 0, 40))
_AURORA_PALETTE: tuple[RGB, ...] = ((0, 130, 95), (0, 190, 150), (40, 95, 225), (130, 40, 205))


def _clamp8(value: float) -> int:
    return max(0, min(255, round(value)))


def _hsv_to_rgb(hue: float, saturation: float, value: float) -> RGB:
    """hue/saturation/value in 0..1 -> RGB. Small, dependency-free."""
    hue = hue % 1.0
    sector = int(hue * 6) % 6
    frac = hue * 6 - int(hue * 6)
    p = value * (1.0 - saturation)
    q = value * (1.0 - frac * saturation)
    t = value * (1.0 - (1.0 - frac) * saturation)
    r, g, b = (
        (value, t, p),
        (q, value, p),
        (p, value, t),
        (p, q, value),
        (t, p, value),
        (value, p, q),
    )[sector]
    return (_clamp8(r * 255), _clamp8(g * 255), _clamp8(b * 255))


def breathing(phase: float, base: RGB) -> RGB:
    """Pulse the base colour's brightness between ~15% and 100% over one cycle."""
    level = 0.15 + 0.85 * (0.5 - 0.5 * math.cos(phase * 2.0 * math.pi))
    return (_clamp8(base[0] * level), _clamp8(base[1] * level), _clamp8(base[2] * level))


def rainbow(phase: float) -> RGB:
    """Smoothly cycle the full hue wheel, fully saturated."""
    return _hsv_to_rgb(phase, 1.0, 1.0)


def candle(phase: float, base: RGB = (255, 120, 30)) -> RGB:
    """Warm flame flicker: layered sines wobble the brightness, hue stays warm.

    Deterministic (no RNG) so it's unit-testable and identical across machines.
    """
    flicker = (
        0.6
        + 0.22 * math.sin(phase * 2.0 * math.pi)
        + 0.12 * math.sin(phase * 2.0 * math.pi * 2.7 + 1.3)
        + 0.06 * math.sin(phase * 2.0 * math.pi * 6.1 + 0.7)
    )
    flicker = max(0.25, min(1.0, flicker))
    return (_clamp8(base[0] * flicker), _clamp8(base[1] * flicker * 0.9), _clamp8(base[2] * flicker * 0.7))


def gradient(phase: float, palette: tuple[RGB, ...] | None = None) -> RGB:
    """Drift smoothly through a colour palette, looping back to the start."""
    palette = palette or _GRADIENT_PALETTE
    count = len(palette)
    position = (phase % 1.0) * count
    index = int(position) % count
    nxt = (index + 1) % count
    frac = position - int(position)
    a, b = palette[index], palette[nxt]
    return (
        _clamp8(a[0] + (b[0] - a[0]) * frac),
        _clamp8(a[1] + (b[1] - a[1]) * frac),
        _clamp8(a[2] + (b[2] - a[2]) * frac),
    )


def heartbeat(phase: float, base: RGB) -> RGB:
    """A double "lub-dub" pulse of the base colour, then a rest — like a pulse."""

    def beat(center: float) -> float:
        x = (phase - center) / 0.05
        return math.exp(-x * x)

    level = 0.12 + 0.88 * min(1.0, beat(0.07) + beat(0.24))
    return (_clamp8(base[0] * level), _clamp8(base[1] * level), _clamp8(base[2] * level))


def storm(phase: float) -> RGB:
    """Dark steel-blue sky with brief bright lightning flashes."""
    spark = max(0.0, math.sin(phase * 2.0 * math.pi * 7.0) * math.sin(phase * 2.0 * math.pi * 13.0 + 1.0))
    flash = spark**6  # sharpen into rare, short flashes
    base_col = (45, 65, 105)
    bright = (225, 232, 255)
    level = 0.05 + 0.95 * flash
    r = base_col[0] + (bright[0] - base_col[0]) * flash
    g = base_col[1] + (bright[1] - base_col[1]) * flash
    b = base_col[2] + (bright[2] - base_col[2]) * flash
    return (_clamp8(r * level), _clamp8(g * level), _clamp8(b * level))


def lava(phase: float) -> RGB:
    """Slow morph through warm reds, oranges and magentas."""
    return gradient(phase, _LAVA_PALETTE)


def aurora(phase: float) -> RGB:
    """Slow morph through cool teals, greens and violets (northern lights)."""
    return gradient(phase, _AURORA_PALETTE)


def render(effect: str, phase: float, base: RGB) -> RGB:
    """Return the colour for ``effect`` at ``phase`` (in cycles, 0..1 loops).

    ``base`` is the current strip colour, used by effects that tint it (breathing).
    Unknown keys fall back to the base colour.
    """
    if effect == "breathing":
        return breathing(phase, base)
    if effect == "heartbeat":
        return heartbeat(phase, base)
    if effect == "rainbow":
        return rainbow(phase)
    if effect == "candle":
        return candle(phase)
    if effect == "storm":
        return storm(phase)
    if effect == "gradient":
        return gradient(phase)
    if effect == "lava":
        return lava(phase)
    if effect == "aurora":
        return aurora(phase)
    return base

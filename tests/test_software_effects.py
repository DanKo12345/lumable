from __future__ import annotations

from app.software_effects import (
    EFFECT_KEYS,
    breathing,
    gradient,
    heartbeat,
    rainbow,
    render,
    storm,
)


def test_heartbeat_beats_brighter_than_rest() -> None:
    base = (200, 100, 50)
    assert heartbeat(0.07, base)[0] > heartbeat(0.6, base)[0]
    assert all(0 <= c <= 255 for c in heartbeat(0.6, base))


def test_storm_is_mostly_dark_with_flashes() -> None:
    levels = [max(storm(i / 500.0)) for i in range(500)]
    assert min(levels) <= 10  # dark steel base most of the time
    assert max(levels) >= 120  # brief bright lightning flashes
    assert all(0 <= channel <= 255 for channel in storm(0.123))


def test_breathing_min_at_zero_max_at_half() -> None:
    base = (200, 100, 50)
    dim = breathing(0.0, base)
    bright = breathing(0.5, base)
    # phase 0 -> trough (~15%), phase 0.5 -> peak (100%).
    assert dim[0] < bright[0]
    assert bright == base  # peak returns the base colour unchanged
    assert all(0 <= c <= 255 for c in dim)


def test_rainbow_cycles_and_wraps() -> None:
    start = rainbow(0.0)
    assert start[0] > start[1] and start[0] > start[2]  # hue 0 -> red
    # Wraps cleanly: phase 1.0 == phase 0.0.
    assert rainbow(1.0) == start


def test_gradient_interpolates_and_clamps() -> None:
    palette = ((0, 0, 0), (255, 255, 255))
    assert gradient(0.0, palette) == (0, 0, 0)
    mid = gradient(0.25, palette)  # quarter into the 0->white leg
    assert all(0 <= c <= 255 for c in mid)
    # Loops back to the first colour.
    assert gradient(1.0, palette) == (0, 0, 0)


def test_render_dispatch_and_fallback() -> None:
    base = (10, 20, 30)
    for key in EFFECT_KEYS:
        color = render(key, 0.3, base)
        assert all(0 <= c <= 255 for c in color)
    # Unknown effect -> base colour unchanged.
    assert render("nope", 0.3, base) == base

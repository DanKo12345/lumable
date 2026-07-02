from __future__ import annotations

from app.software_effects import (
    EFFECT_KEYS,
    breathing,
    gradient,
    heartbeat,
    ocean,
    police,
    rainbow,
    render,
    storm,
    strobe,
    sunset,
    twinkle,
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


def test_ocean_and_sunset_stay_in_character() -> None:
    # Ocean drifts through cool blues/teals: blue channel leads across the cycle.
    assert all(ocean(i / 20.0)[2] >= ocean(i / 20.0)[0] for i in range(20))
    # Sunset is warm: red channel dominates blue across the cycle.
    assert all(sunset(i / 20.0)[0] >= sunset(i / 20.0)[2] for i in range(20))
    assert all(0 <= c <= 255 for c in ocean(0.4))
    assert all(0 <= c <= 255 for c in sunset(0.4))


def test_twinkle_mostly_dim_with_rare_flashes() -> None:
    base = (200, 180, 120)
    levels = [max(twinkle(i / 500.0, base)) for i in range(500)]
    assert min(levels) <= max(base) * 0.30  # sits dim most of the time
    assert max(levels) >= max(base) * 0.85  # brief bright sparkle


def test_strobe_blinks_hard_on_and_off() -> None:
    base = (120, 200, 60)
    assert strobe(0.0, base) == base  # on phase -> full base colour
    assert all(c <= 20 for c in strobe(0.1, base))  # off phase -> nearly black


def test_police_alternates_red_and_blue() -> None:
    # First half of the cycle is red-dominant, second half blue-dominant.
    reds = [police(0.02 + i * 0.001) for i in range(5)]
    blues = [police(0.52 + i * 0.001) for i in range(5)]
    assert any(c[0] > c[2] for c in reds)
    assert any(c[2] > c[0] for c in blues)
    assert all(0 <= ch <= 255 for c in reds + blues for ch in c)


def test_render_dispatch_and_fallback() -> None:
    base = (10, 20, 30)
    for key in EFFECT_KEYS:
        color = render(key, 0.3, base)
        assert all(0 <= c <= 255 for c in color)
    # Unknown effect -> base colour unchanged.
    assert render("nope", 0.3, base) == base

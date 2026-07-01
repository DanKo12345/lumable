from __future__ import annotations

from app.color_temperature import (
    MAX_KELVIN,
    MIN_KELVIN,
    cct_to_rgb,
)


def test_neutral_daylight_is_near_white() -> None:
    r, g, b = cct_to_rgb(6600)
    assert r > 240 and g > 240 and b > 240


def test_warm_is_red_dominant() -> None:
    r, g, b = cct_to_rgb(2000)
    assert r == 255
    assert r > g > b  # warm: lots of red, little blue


def test_cool_is_blue_dominant() -> None:
    r, _g, b = cct_to_rgb(10000)
    assert b == 255
    assert b > r  # cool: blue outweighs red


def test_output_channels_in_range() -> None:
    for kelvin in range(MIN_KELVIN, MAX_KELVIN + 1, 250):
        for channel in cct_to_rgb(kelvin):
            assert 0 <= channel <= 255


def test_clamps_out_of_range_input() -> None:
    assert cct_to_rgb(-500) == cct_to_rgb(MIN_KELVIN)
    assert cct_to_rgb(99999) == cct_to_rgb(MAX_KELVIN)


def test_warmer_has_more_red_bias_than_cooler() -> None:
    warm_r, _, warm_b = cct_to_rgb(2700)
    cool_r, _, cool_b = cct_to_rgb(6500)
    # red/blue balance shifts from red toward blue as temperature rises
    assert (warm_r - warm_b) > (cool_r - cool_b)

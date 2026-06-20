from __future__ import annotations

from app.ambient_color import average_color, shape_color


def _bgra(pixels: list[tuple[int, int, int]]) -> bytes:
    # mss buffers are BGRA; alpha is ignored by average_color.
    out = bytearray()
    for r, g, b in pixels:
        out += bytes((b, g, r, 255))
    return bytes(out)


def test_average_color_of_uniform_buffer() -> None:
    buffer = _bgra([(10, 20, 30)] * 16)
    assert average_color(buffer, channels=4, sample_step=1) == (10, 20, 30)


def test_average_color_mixes_pixels() -> None:
    buffer = _bgra([(0, 0, 0), (100, 100, 100)])
    assert average_color(buffer, channels=4, sample_step=1) == (50, 50, 50)


def test_average_color_empty_is_black() -> None:
    assert average_color(b"", channels=4) == (0, 0, 0)


def test_shape_color_boosts_saturation_but_keeps_grey_grey() -> None:
    # Grey has no saturation, so boosting it changes nothing.
    assert shape_color((120, 120, 120), saturation=2.0, gamma=1.0) == (120, 120, 120)


def test_shape_color_increases_saturation_of_a_tint() -> None:
    washed = (180, 150, 150)  # slightly reddish
    boosted = shape_color(washed, saturation=2.0, gamma=1.0)
    # red stays the dominant channel and the gap to the others widens
    assert boosted[0] >= washed[0]
    assert (boosted[0] - boosted[1]) > (washed[0] - washed[1])


def test_shape_color_min_brightness_lifts_black() -> None:
    lifted = shape_color((0, 0, 0), min_brightness=40)
    assert max(lifted) >= 40


def test_shape_color_max_brightness_caps_white() -> None:
    capped = shape_color((255, 255, 255), max_brightness=128)
    assert max(capped) <= 130

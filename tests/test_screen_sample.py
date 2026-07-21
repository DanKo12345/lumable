"""Spatial frame analysis: what colour comes out of a single frame.

These are all synthetic frames with a known answer — no screen, no event loop,
no previous frames. That is the whole point of keeping the spatial stage pure
and stateless.
"""

from __future__ import annotations

import math

from app.screen_sample import RGB, SampleConfig, detect_active_rect, extract_color, sample_step_for


def _frame(width: int, height: int, pixel) -> bytes:
    """A BGRA buffer whose pixel (x, y) = pixel(x, y) as an (r, g, b) tuple."""
    out = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            r, g, b = pixel(x, y)
            i = (y * width + x) * 4
            out[i] = b
            out[i + 1] = g
            out[i + 2] = r
            out[i + 3] = 255
    return bytes(out)


def _solid(width: int, height: int, rgb: RGB) -> bytes:
    return _frame(width, height, lambda _x, _y: rgb)


# ── frame-format contract ─────────────────────────────────────────────

def test_pixel_offset_is_row_major_bgra() -> None:
    # One red pixel at (3, 2) on black; a uniform-ish extraction must read red.
    def pixel(x, y):
        return (255, 0, 0) if (x, y) == (3, 2) else (0, 0, 0)

    buffer = _frame(6, 4, pixel)
    # Dominant colour of an otherwise black frame with a single red pixel is red.
    r, g, b = extract_color(buffer, 6, 4, SampleConfig(reject_black_bars=False, edge_weight=0.0))
    assert r > g and r > b


def test_short_buffer_is_black() -> None:
    assert extract_color(b"\x00\x00", 100, 100) == (0, 0, 0)


# ── uniform / blend ───────────────────────────────────────────────────

def test_uniform_frame_returns_that_colour() -> None:
    buffer = _solid(20, 20, (40, 90, 160))
    assert extract_color(buffer, 20, 20, SampleConfig(dominant=False)) == (40, 90, 160)


# ── black-bar rejection ───────────────────────────────────────────────

def test_letterbox_bars_are_trimmed() -> None:
    # Top and bottom thirds are black bars; the middle is solid green.
    def pixel(_x, y):
        return (0, 200, 0) if 10 <= y < 20 else (0, 0, 0)

    buffer = _frame(30, 30, pixel)
    rect = detect_active_rect(buffer, 30, 30)
    assert rect.top >= 8 and rect.bottom <= 22  # bars trimmed
    # With the bars gone the colour is the green content, not a dark average.
    r, g, b = extract_color(buffer, 30, 30, SampleConfig())
    assert g > 120 and g > r and g > b


def test_black_bars_ignored_when_rejection_off() -> None:
    def pixel(_x, y):
        return (0, 200, 0) if 10 <= y < 20 else (0, 0, 0)

    buffer = _frame(30, 30, pixel)
    off = extract_color(buffer, 30, 30, SampleConfig(reject_black_bars=False, dominant=False))
    on = extract_color(buffer, 30, 30, SampleConfig(reject_black_bars=True, dominant=False))
    assert on[1] > off[1]  # rejecting the bars makes the green stronger


def test_a_dark_scene_is_not_swallowed_as_one_big_bar() -> None:
    # Uniformly dim blue: no real bars, so nothing should be trimmed to nothing.
    buffer = _solid(40, 40, (0, 0, 30))
    rect = detect_active_rect(buffer, 40, 40)
    assert rect.width == 40 and rect.height == 40


def test_combined_letterbox_and_pillarbox_is_trimmed_on_all_sides() -> None:
    # A pillar-and-letterboxed frame: black border all round, colour in a central
    # window. All four sides must be trimmed to the content.
    def pixel(x, y):
        inside = 8 <= x < 32 and 6 <= y < 34
        return (0, 160, 220) if inside else (0, 0, 0)

    buffer = _frame(40, 40, pixel)
    rect = detect_active_rect(buffer, 40, 40)
    assert rect.left >= 6 and rect.right <= 34
    assert rect.top >= 4 and rect.bottom <= 36
    r, g, b = extract_color(buffer, 40, 40, SampleConfig())
    assert b > 120 and g > 90 and r < 90  # the cyan content, not a dark average


# ── edge weighting ────────────────────────────────────────────────────

def test_edge_weighting_favours_the_border() -> None:
    # Red border ring, blue centre. Edge weighting should lean red; turning it
    # off (uniform) should lean blue (the centre is the larger area).
    def pixel(x, y):
        near_edge = x < 4 or x >= 36 or y < 4 or y >= 36
        return (220, 0, 0) if near_edge else (0, 0, 220)

    buffer = _frame(40, 40, pixel)
    edged = extract_color(buffer, 40, 40, SampleConfig(edge_weight=4.0, dominant=False))
    flat = extract_color(buffer, 40, 40, SampleConfig(edge_weight=0.0, dominant=False))
    assert edged[0] > flat[0]  # more red when the border is weighted up


# ── dominant colour ───────────────────────────────────────────────────

def test_dominant_ignores_a_grey_majority() -> None:
    # 80% mid-grey, 20% saturated magenta cluster. Dominant should be magenta,
    # a plain blend would be a greyish pink.
    def pixel(x, _y):
        return (200, 0, 200) if x < 8 else (128, 128, 128)

    buffer = _frame(40, 20, pixel)
    dom = extract_color(buffer, 40, 20, SampleConfig(dominant=True, edge_weight=0.0))
    assert dom[0] > 150 and dom[2] > 150 and dom[1] < 90  # magenta, not grey


def test_dominant_falls_back_to_grey_when_there_is_no_colour() -> None:
    buffer = _solid(20, 20, (120, 120, 120))
    dom = extract_color(buffer, 20, 20, SampleConfig(dominant=True))
    assert abs(dom[0] - 120) <= 6 and abs(dom[1] - 120) <= 6 and abs(dom[2] - 120) <= 6


# ── 2-D sample step ───────────────────────────────────────────────────

def test_sample_step_hits_the_target_count_on_full_hd() -> None:
    step = sample_step_for(1920, 1080, target_samples=2500)
    # A linear pixels // target would be ~830 here (≈6 samples in a 2-D grid).
    assert 25 <= step <= 33
    samples = math.ceil(1920 / step) * math.ceil(1080 / step)
    assert 1800 <= samples <= 3400  # near 2500, not six


def test_sample_step_never_below_one() -> None:
    assert sample_step_for(10, 10, target_samples=2500) == 1

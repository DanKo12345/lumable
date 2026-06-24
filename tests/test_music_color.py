from __future__ import annotations

from app.music_color import DEFAULT_BAND_COLORS, bands_to_rgb, normalize_level


def test_custom_band_colors_recolor_bands() -> None:
    # Swap defaults: make bass -> blue. A bass-dominant signal should now be blue.
    colors = ((0, 0, 255), (0, 255, 0), (255, 0, 0))
    blue = bands_to_rgb(1.0, 0.0, 0.0, 1.0, colors=colors)
    assert blue[2] > blue[0] and blue[2] > blue[1]
    # Treble now maps to red.
    red = bands_to_rgb(0.0, 0.0, 1.0, 1.0, colors=colors)
    assert red[0] > red[1] and red[0] > red[2]


def test_default_colors_are_valid_rgb_triples() -> None:
    assert len(DEFAULT_BAND_COLORS) == 3
    for color in DEFAULT_BAND_COLORS:
        assert len(color) == 3
        assert all(0 <= channel <= 255 for channel in color)


def test_normalize_level_silence_and_saturation() -> None:
    assert normalize_level(0.0) == 0.0
    assert normalize_level(0.001) == 0.0  # below noise floor
    assert normalize_level(1.0) == 1.0  # well above ceiling -> saturates
    # Monotonic between floor and ceiling.
    assert normalize_level(0.05) < normalize_level(0.15)


def test_bands_to_rgb_dominant_band_sets_hue() -> None:
    # Use explicit pure R/G/B so the test checks the mapping mechanism, not the
    # (tunable) default palette.
    rgb = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
    red = bands_to_rgb(1.0, 0.0, 0.0, 1.0, colors=rgb)
    assert red[0] > red[1] and red[0] > red[2]

    blue = bands_to_rgb(0.0, 0.0, 1.0, 1.0, colors=rgb)
    assert blue[2] > blue[0] and blue[2] > blue[1]

    green = bands_to_rgb(0.0, 1.0, 0.0, 1.0, colors=rgb)
    assert green[1] > green[0] and green[1] > green[2]


def test_bands_to_rgb_level_controls_brightness() -> None:
    quiet = bands_to_rgb(1.0, 0.0, 0.0, 0.3)
    loud = bands_to_rgb(1.0, 0.0, 0.0, 1.0)
    assert loud[0] > quiet[0]


def test_bands_to_rgb_silence_is_dim_not_black() -> None:
    dim = bands_to_rgb(1.0, 0.0, 0.0, 0.0, floor_brightness=0.06)
    # A small floor glow, never fully off, never clipping.
    assert 0 < dim[0] <= 20


def test_bands_to_rgb_always_clamped() -> None:
    for color in (
        bands_to_rgb(5.0, 5.0, 5.0, 1.0, saturation=3.0),
        bands_to_rgb(0.0, 0.0, 0.0, 1.0),
        bands_to_rgb(1.0, 0.2, 0.1, 2.0),
    ):
        for channel in color:
            assert 0 <= channel <= 255

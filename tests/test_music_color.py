from __future__ import annotations

import pytest

from app.music_color import DEFAULT_BAND_COLORS, bands_to_rgb, normalize_level, update_beat


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


def test_update_beat_warmup_seeds_average_without_firing() -> None:
    avg, env, is_beat = update_beat(1.0, 0.0, 0.0)
    assert avg == 1.0
    assert env == 0.0
    assert is_beat is False


def test_update_beat_fires_on_spike() -> None:
    # Average settled low, then a loud bass block jumps above the threshold.
    _avg, env, is_beat = update_beat(5.0, 1.0, 0.0, sensitivity=1.3)
    assert is_beat is True
    assert env == 1.0


def test_update_beat_does_not_retrigger_while_pulse_high() -> None:
    # Right after a beat (env=1.0) another loud block must not fire again.
    _avg, _env, is_beat = update_beat(5.0, 1.0, 1.0, sensitivity=1.3)
    assert is_beat is False


def test_update_beat_envelope_decays_without_a_beat() -> None:
    _avg, env, is_beat = update_beat(0.5, 1.0, 0.8, sensitivity=1.3, decay=0.5)
    assert is_beat is False  # 0.5 is below 1.3x the average
    assert env == pytest.approx(0.4)  # 0.8 * 0.5

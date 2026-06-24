from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from app.music_controller import analyze_block  # noqa: E402  (after importorskip)

_SR = 48000
_N = 1024


def _sine(freq: float, amp: float = 0.5):
    t = np.arange(_N) / _SR
    return amp * np.sin(2 * np.pi * freq * t)


def test_bass_tone_is_bass_dominant() -> None:
    bass, mid, treble, _rms = analyze_block(_sine(100), _SR)
    assert bass > mid and bass > treble


def test_treble_tone_is_treble_dominant() -> None:
    bass, mid, treble, _rms = analyze_block(_sine(6000), _SR)
    assert treble > bass and treble > mid


def test_silence_is_zero() -> None:
    assert analyze_block(np.zeros(_N), _SR) == (0.0, 0.0, 0.0, 0.0)


def test_rms_matches_sine_amplitude() -> None:
    *_bands, rms = analyze_block(_sine(100, amp=0.5), _SR)
    assert rms == pytest.approx(0.354, abs=0.02)  # 0.5 / sqrt(2)


def test_stereo_is_downmixed() -> None:
    stereo = np.stack([_sine(100), _sine(100)], axis=1)
    bass, mid, treble, _rms = analyze_block(stereo, _SR)
    assert bass > mid and bass > treble


def test_empty_block_is_safe() -> None:
    assert analyze_block(np.zeros((0,)), _SR) == (0.0, 0.0, 0.0, 0.0)

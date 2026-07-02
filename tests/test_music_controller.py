from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from app.music_controller import MusicController, MusicOptions, analyze_block  # noqa: E402  (after importorskip)

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


class _FakeMic:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSpeaker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.id = name


class _FakeSc:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_microphone(self, name, include_loopback=False):
        self.calls.append(("get_microphone", name, include_loopback))
        return _FakeMic(f"loopback:{name}" if include_loopback else name)

    def default_microphone(self):
        return _FakeMic("default-mic")

    def all_microphones(self, include_loopback=False):
        return [_FakeMic("MyMic")]

    def default_speaker(self):
        return _FakeSpeaker("default-speaker")

    def all_speakers(self):
        return [_FakeSpeaker("Speakers")]

    def get_speaker(self, name):
        return _FakeSpeaker(name)


def test_system_source_uses_speaker_loopback() -> None:
    sc = _FakeSc()
    dev = MusicController._open_recorder_source(sc, MusicOptions(source="system", device_name=""))
    assert dev.name == "loopback:default-speaker"
    assert ("get_microphone", "default-speaker", True) in sc.calls


class _FakeSd:
    def __init__(self, devices: list[dict]) -> None:
        self._devices = devices

    def query_devices(self, *args, **kwargs):
        return self._devices


def test_resolve_sd_input_matches_input_by_name() -> None:
    sd = _FakeSd([
        {"name": "Speakers (Realtek)", "max_input_channels": 0},
        {"name": "Microphone (RODE NT-USB)", "max_input_channels": 1},
    ])
    # Skips the output-only device, matches the mic by substring -> its index.
    assert MusicController._resolve_sd_input(sd, "RODE") == 1


def test_resolve_sd_input_defaults_to_none() -> None:
    sd = _FakeSd([{"name": "Mic", "max_input_channels": 2}])
    assert MusicController._resolve_sd_input(sd, "") is None            # empty -> default input
    assert MusicController._resolve_sd_input(sd, "Nonexistent") is None  # no match -> default input

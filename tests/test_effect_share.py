from __future__ import annotations

from app.effect_share import SHARE_PREFIX, decode_effect, encode_effect

_EFFECT = {
    "name": "Sunset vibes",
    "steps": [
        {"rgb": [255, 80, 20], "duration_ms": 1500, "motion": "breathe"},
        {"rgb": [40, 20, 120], "duration_ms": 800, "motion": "none"},
        {"rgb": [0, 200, 205], "duration_ms": 1200, "motion": "pulse"},
    ],
    "transition": "cut",
    "speed": 70,
}


def test_round_trip_preserves_effect() -> None:
    code = encode_effect(_EFFECT)
    assert code.startswith(SHARE_PREFIX)
    decoded = decode_effect(code)
    assert decoded is not None
    assert decoded["name"] == "Sunset vibes"
    assert decoded["transition"] == "cut"
    assert decoded["speed"] == 70
    assert decoded["steps"] == _EFFECT["steps"]


def test_decode_rejects_garbage() -> None:
    assert decode_effect("not a code") is None
    assert decode_effect("") is None
    assert decode_effect(SHARE_PREFIX + "@@@notbase64@@@") is None
    assert decode_effect(None) is None  # type: ignore[arg-type]


def test_decode_rejects_wrong_prefix_or_version() -> None:
    good = encode_effect(_EFFECT)
    body = good[len(SHARE_PREFIX):]
    assert decode_effect("LUMA9-" + body) is None  # unknown prefix
    # A payload with too few steps is rejected.
    assert decode_effect(encode_effect({**_EFFECT, "steps": _EFFECT["steps"][:1]})) is None


def test_encode_clamps_and_sanitises() -> None:
    messy = {
        "name": "x" * 80,
        "steps": [
            {"rgb": [999, -5, 50], "duration_ms": 999999, "motion": "bogus"},
            {"rgb": [10, 20, 30], "duration_ms": 500, "motion": "strobe"},
        ],
        "transition": "weird",
        "speed": 250,
    }
    decoded = decode_effect(encode_effect(messy))
    assert decoded is not None
    assert len(decoded["name"]) == 40
    assert decoded["transition"] == "smooth"  # unknown -> smooth
    assert decoded["speed"] == 100  # clamped
    first = decoded["steps"][0]
    assert first["rgb"] == [255, 0, 50]
    assert first["duration_ms"] == 10_000
    assert first["motion"] == "none"  # unknown motion -> none

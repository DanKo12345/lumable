"""The three pure stages composed in the order the strip actually sees.

Order matters: spatial extract → shape (gamma/saturation/floors) → temporal
(smoothing + flash limiter). The flash limiter must run *last*, or the shaping's
non-linear gamma/saturation could re-amplify a jump it just capped. These tests
compose the real functions to pin that guarantee — no controller, no screen.
"""

from __future__ import annotations

from app.ambient_color import shape_color
from app.screen_sample import SampleConfig, extract_color
from app.screen_temporal import TemporalConfig, TemporalFilter


def _solid_bgra(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    r, g, b = rgb
    return bytes((b, g, r, 255)) * (width * height)


def _run(frames, temporal: TemporalFilter, dt: float):
    out = []
    for buf, w, h in frames:
        raw = extract_color(buf, w, h, SampleConfig(reject_black_bars=False))
        shaped = shape_color(raw, saturation=1.4, gamma=1.1, min_saturation=0.2)
        out.append(temporal.push(shaped, dt=dt))
    return out


def test_flash_is_bounded_on_the_final_output_after_shaping() -> None:
    # A hard cut from black to saturated red. Even though shape_color boosts
    # saturation and gamma, the final per-frame change must stay within the cap.
    black = (_solid_bgra(8, 8, (0, 0, 0)), 8, 8)
    red = (_solid_bgra(8, 8, (255, 0, 0)), 8, 8)
    dt = 1 / 12
    temporal = TemporalFilter(TemporalConfig(half_life_s=1e-6, max_rate=300))  # ~25/frame at 12fps
    frames = [black] + [red] * 6

    outputs = _run(frames, temporal, dt)
    prev = outputs[0]
    for cur in outputs[1:]:
        assert all(abs(c - p) <= 26 for c, p in zip(cur, prev, strict=True))  # cap ~25 + rounding
        prev = cur
    assert outputs[-1][0] < 200  # six capped steps have not reached full red yet


def test_saturation_floor_lifts_a_washed_colour() -> None:
    washed = (150, 120, 120)  # clearly reddish, above the noise floor
    floored = shape_color(washed, saturation=1.0, gamma=1.0, min_saturation=0.6)
    plain = shape_color(washed, saturation=1.0, gamma=1.0, min_saturation=0.0)
    assert (floored[0] - floored[1]) > (plain[0] - plain[1])  # clearly more saturated


def test_saturation_floor_leaves_true_grey_grey() -> None:
    grey = shape_color((120, 120, 120), saturation=2.0, gamma=1.0, min_saturation=0.8)
    assert grey == (120, 120, 120)  # no hue to floor — not tinted an arbitrary colour


def test_saturation_floor_ignores_near_grey_noise() -> None:
    # One channel off by a single step is sensor/JPEG noise, not a colour. The
    # dead zone must leave it alone, or grey UIs would jitter between vivid hues.
    noisy = shape_color((121, 120, 120), saturation=1.0, gamma=1.0, min_saturation=0.8)
    assert max(noisy) - min(noisy) <= 2  # stayed grey, not pulled to a vivid red


def test_saturation_floor_gate_survives_a_strong_boost() -> None:
    # The gate is judged on the original colour, so even a punchy profile's boost
    # must not push faint noise past the dead zone and colour it.
    noisy = shape_color((125, 120, 120), saturation=2.5, gamma=1.0, min_saturation=0.8)
    assert max(noisy) - min(noisy) <= 6  # still essentially grey


def test_saturation_floor_ignores_dark_near_grey() -> None:
    # (5,3,3): HSV saturation is formally high (0.4) but the real chroma is two
    # levels — the absolute-chroma gate keeps it grey.
    dark = shape_color((5, 3, 3), saturation=2.5, gamma=1.0, min_saturation=0.8)
    assert max(dark) - min(dark) <= 3


def test_chroma_gate_has_no_hard_edge() -> None:
    # Adjacent inputs across the old chroma threshold (8) must not jump: a hard
    # gate would flip a strong profile from no boost to full boost on one level.
    def chroma(rgb):
        out = shape_color(rgb, saturation=2.5, gamma=1.0, min_saturation=0.8)
        return max(out) - min(out)

    below = chroma((128, 120, 120))   # chroma 8
    just_over = chroma((129, 120, 120))  # chroma 9
    assert just_over - below <= 12  # smooth ramp, not a leap to full saturation
    # And well past the ramp, the floor really does engage.
    strong = chroma((150, 120, 120))  # chroma 30
    assert strong > just_over + 20


def test_settled_output_reaches_the_shaped_target() -> None:
    green = (_solid_bgra(8, 8, (0, 180, 0)), 8, 8)
    temporal = TemporalFilter(TemporalConfig(half_life_s=0.05, max_rate=100000))
    outputs = _run([green] * 40, temporal, dt=1 / 12)
    expected = shape_color(
        extract_color(green[0], 8, 8, SampleConfig(reject_black_bars=False)),
        saturation=1.4,
        gamma=1.1,
        min_saturation=0.2,
    )
    assert all(abs(c - e) <= 2 for c, e in zip(outputs[-1], expected, strict=True))

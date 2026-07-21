"""End-to-end behaviour of the screen-sync pipeline, per profile.

Not "are the numbers right" (that's test_screen_profiles) but "does the whole
recipe behave" — the same synthetic frame stream driven through Desktop / Game /
Movie must show the character of each: Game reacts faster than Movie, Desktop
lifts a black frame (bias light), and Movie leaves it black once settled. All by
feeding frames to the pure stages in the controller's order, no screen involved.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

from app.ambient_color import shape_color
from app.screen_profiles import get_profile, resolve_configs
from app.screen_sample import extract_color, sample_step_for
from app.screen_temporal import TemporalFilter


def _solid_bgra(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    r, g, b = rgb
    return bytes((b, g, r, 255)) * (width * height)


def _pipeline(profile_id: str, frames, dt: float, *, seed=(0, 0, 0)):
    """Run frames through spatial → shape → temporal, exactly as the controller
    does, and return the list of final colours."""
    resolved = resolve_configs(get_profile(profile_id), 55, 65)  # neutral nudges
    temporal = TemporalFilter(initial=seed)
    temporal.set_config(resolved.temporal)
    out = []
    for buf, w, h in frames:
        sample = replace(resolved.sample, sample_step=sample_step_for(w, h))
        raw = extract_color(buf, w, h, sample)
        shaped = shape_color(
            raw,
            saturation=resolved.shape.saturation,
            gamma=resolved.shape.gamma,
            min_brightness=resolved.shape.min_brightness,
            max_brightness=resolved.shape.max_brightness,
            min_saturation=resolved.shape.min_saturation,
        )
        out.append(temporal.push(shaped, dt))
    return out


def test_game_reacts_faster_than_movie() -> None:
    # A hard cut from black to bright blue; after the same short time Game must
    # be closer to the target than Movie.
    blue = (_solid_bgra(16, 16, (0, 0, 255)), 16, 16)
    frames = [blue] * 6
    dt = 1 / 30
    game = _pipeline("game", frames, dt)[-1]
    movie = _pipeline("movie", frames, dt)[-1]
    assert game[2] > movie[2]  # Game's blue has climbed further


def test_desktop_lifts_a_black_frame_as_a_bias_light() -> None:
    black = (_solid_bgra(16, 16, (0, 0, 0)), 16, 16)
    settled = _pipeline("desktop", [black] * 60, dt=1 / 30, seed=(0, 0, 0))[-1]
    assert max(settled) >= get_profile("desktop").shape.min_brightness - 2


def test_movie_leaves_true_black_black() -> None:
    black = (_solid_bgra(16, 16, (0, 0, 0)), 16, 16)
    settled = _pipeline("movie", [black] * 60, dt=1 / 30, seed=(0, 0, 0))[-1]
    assert max(settled) <= 4  # no bias floor — the room stays dark for film


def test_movie_ignores_letterbox_bars() -> None:
    # 21:9 content letterboxed into 16:9: black top/bottom, green middle. Movie
    # rejects the bars, so the strip shows the content, not a dark average.
    def pixel(_x, y):
        return (0, 200, 0) if 6 <= y < 18 else (0, 0, 0)

    buf = bytearray(24 * 24 * 4)
    for y in range(24):
        for x in range(24):
            r, g, b = pixel(x, y)
            i = (y * 24 + x) * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = b, g, r, 255
    frame = (bytes(buf), 24, 24)
    settled = _pipeline("movie", [frame] * 60, dt=1 / 30)[-1]
    assert settled[1] > settled[0] and settled[1] > settled[2]  # green wins


def test_a_flash_never_strobes_the_output() -> None:
    # Alternating black/white every frame (a strobe) must not reach the output as
    # a strobe: the flash limiter keeps consecutive outputs close together.
    black = (_solid_bgra(16, 16, (0, 0, 0)), 16, 16)
    white = (_solid_bgra(16, 16, (255, 255, 255)), 16, 16)
    frames = [white if i % 2 else black for i in range(12)]
    outputs = _pipeline("game", frames, dt=1 / 30)  # Game has the highest flash rate
    for prev, cur in pairwise(outputs):
        assert all(abs(c - p) <= 75 for c, p in zip(cur, prev, strict=True))  # bounded, not 0↔255

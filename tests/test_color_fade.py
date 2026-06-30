from __future__ import annotations

from app.color_fade import color_distance, fade_frames, lerp_rgb


def test_lerp_endpoints_and_midpoint() -> None:
    start, end = (0, 0, 0), (100, 200, 50)
    assert lerp_rgb(start, end, 0.0) == (0, 0, 0)
    assert lerp_rgb(start, end, 1.0) == (100, 200, 50)
    assert lerp_rgb(start, end, 0.5) == (50, 100, 25)


def test_lerp_clamps_t() -> None:
    assert lerp_rgb((0, 0, 0), (10, 10, 10), -1.0) == (0, 0, 0)
    assert lerp_rgb((0, 0, 0), (10, 10, 10), 2.0) == (10, 10, 10)


def test_color_distance_is_max_channel_diff() -> None:
    assert color_distance((0, 0, 0), (0, 0, 0)) == 0
    assert color_distance((10, 20, 30), (10, 20, 90)) == 60
    assert color_distance((255, 0, 0), (0, 0, 0)) == 255


def test_fade_frames_count_and_endpoints() -> None:
    frames = fade_frames((0, 0, 0), (80, 0, 0), 4)
    assert len(frames) == 4
    assert frames[-1] == (80, 0, 0)  # last frame is the target
    assert frames[0] != (0, 0, 0)  # excludes the start
    # Monotonic increase toward the target on the changing channel.
    reds = [frame[0] for frame in frames]
    assert reds == sorted(reds)


def test_fade_frames_min_one_step() -> None:
    assert fade_frames((0, 0, 0), (10, 10, 10), 0) == [(10, 10, 10)]

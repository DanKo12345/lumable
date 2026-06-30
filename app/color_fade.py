from __future__ import annotations

RGB = tuple[int, int, int]


def lerp_rgb(start: RGB, end: RGB, t: float) -> RGB:
    """Linearly interpolate between two RGB colours at ``t`` in 0..1."""
    t = max(0.0, min(1.0, t))
    return (
        round(start[0] + (end[0] - start[0]) * t),
        round(start[1] + (end[1] - start[1]) * t),
        round(start[2] + (end[2] - start[2]) * t),
    )


def color_distance(a: RGB, b: RGB) -> int:
    """Largest per-channel difference between two colours (0..255).

    Used to skip the fade for tiny changes (e.g. dragging a slider a notch),
    so only real scene jumps animate.
    """
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def fade_frames(start: RGB, end: RGB, steps: int) -> list[RGB]:
    """Intermediate colours from ``start`` toward ``end`` (excluding start,
    including end). ``steps`` frames total; the last frame equals ``end``."""
    steps = max(1, int(steps))
    return [lerp_rgb(start, end, index / steps) for index in range(1, steps + 1)]

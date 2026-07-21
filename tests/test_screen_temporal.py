"""The temporal filter, driven by a plain sequence of colours — no screen.

Every behaviour (time-based easing, the flash cap, reset, frame-rate
independence) is checked deterministically without capturing anything.
"""

from __future__ import annotations

from app.screen_temporal import TemporalConfig, TemporalFilter


def test_first_colour_is_shown_as_is() -> None:
    f = TemporalFilter()
    assert f.push((10, 20, 30), dt=1 / 12) == (10, 20, 30)


def test_converges_toward_a_held_colour() -> None:
    f = TemporalFilter(TemporalConfig(half_life_s=0.05, max_rate=100000))
    f.push((0, 0, 0), dt=1 / 12)
    seen = [f.push((100, 0, 0), dt=1 / 12)[0] for _ in range(30)]
    assert seen[0] < 100          # it eases in, not a jump
    assert seen[-1] >= 99         # and gets there
    assert seen == sorted(seen)   # monotonic approach, never overshoots


def test_flash_limiter_caps_change_per_second_not_per_frame() -> None:
    # max_rate is per-second, so the same wall-clock time gives the same total
    # change regardless of how many frames it was split into. Both runs cover
    # exactly 0.25 s of a hard cut to white (tiny half-life = the cap dominates).
    def travel(dt: float, frames: int) -> int:
        f = TemporalFilter(TemporalConfig(half_life_s=1e-6, max_rate=300))
        f.push((0, 0, 0), dt=dt)
        value = 0
        for _ in range(frames):
            value = f.push((255, 255, 255), dt=dt)[0]
        return value

    fast = travel(1 / 24, 6)  # 0.25 s at 24 fps
    slow = travel(1 / 12, 3)  # 0.25 s at 12 fps
    assert abs(fast - slow) <= 3          # frame-rate independent
    assert 70 <= slow <= 80               # ~ max_rate * 0.25s = 75, not a full flash


def test_frame_rate_independent_easing() -> None:
    # Same wall-clock, different fps → nearly the same place.
    def run(dt: float) -> int:
        f = TemporalFilter(TemporalConfig(half_life_s=0.08, max_rate=100000))
        f.push((0, 0, 0), dt=dt)
        out = 0
        for _ in range(round(0.4 / dt)):
            out = f.push((200, 0, 0), dt=dt)[0]
        return out

    assert abs(run(1 / 12) - run(1 / 60)) <= 6


def test_a_stall_does_not_teleport() -> None:
    # A huge dt (thread hitch) is clamped, and the absolute max_step bounds the
    # update, so even a 10 s gap cannot flash the strip.
    f = TemporalFilter(TemporalConfig(half_life_s=0.1, max_rate=480, max_step=60))
    f.push((0, 0, 0), dt=1 / 12)
    out = f.push((255, 255, 255), dt=10.0)
    assert out[0] <= 60  # absolute cap, not max_rate * clamped_dt (= 240)


def test_seeded_first_frame_is_rate_limited() -> None:
    # Seeding from the strip's colour means even the first frame after a start
    # or profile switch cannot flash — reset(black) then a white frame ramps.
    f = TemporalFilter(TemporalConfig(half_life_s=0.05, max_rate=300, max_step=60), initial=(0, 0, 0))
    out = f.push((255, 255, 255), dt=1 / 12)
    assert out[0] <= 60

    f.reset((0, 0, 0))
    out = f.push((255, 255, 255), dt=1 / 12)
    assert out[0] <= 60


def test_unseeded_first_frame_is_shown_as_is() -> None:
    f = TemporalFilter(TemporalConfig(max_step=60))
    assert f.push((255, 255, 255), dt=1 / 12) == (255, 255, 255)  # no seed → as-is


def test_reset_forgets_history() -> None:
    f = TemporalFilter(TemporalConfig(half_life_s=0.5, max_rate=20))
    f.push((0, 0, 0), dt=1 / 12)
    f.push((255, 255, 255), dt=1 / 12)  # barely moves off black
    f.reset()
    assert f.push((200, 100, 50), dt=1 / 12) == (200, 100, 50)  # shown as-is again
    assert f.last == (200, 100, 50)


def test_values_are_clamped() -> None:
    # max_step high so the caps don't mask the 0..255 clamping under test.
    f = TemporalFilter(TemporalConfig(half_life_s=1e-6, max_rate=100000, max_step=100000))
    f.push((0, 0, 0), dt=1 / 12)
    assert f.push((300, -20, 128), dt=1 / 12) == (255, 0, 128)

from __future__ import annotations

from app.color_stream import ColorSmoother


def test_smoother_eases_toward_target_and_settles() -> None:
    smoother = ColorSmoother(smoothing=0.5)
    smoother.reset((0, 0, 0))
    smoother.set_target((255, 0, 0))

    first = smoother.advance()
    assert 100 < first[0] < 160  # halfway-ish on the first step
    assert first[1] == 0 and first[2] == 0

    for _ in range(40):
        smoother.advance()
    assert smoother.advance() == (255, 0, 0)
    assert smoother.at_target()


def test_smoother_clamps_out_of_range_targets() -> None:
    smoother = ColorSmoother(smoothing=1.0)
    smoother.reset((0, 0, 0))
    smoother.set_target((999, -20, 300))
    assert smoother.advance() == (255, 0, 255)


def test_smoother_no_movement_when_already_at_target() -> None:
    smoother = ColorSmoother(smoothing=0.4)
    smoother.reset((30, 60, 90))
    smoother.set_target((30, 60, 90))
    assert smoother.advance() == (30, 60, 90)
    assert smoother.at_target()


def test_smoothing_factor_is_bounded() -> None:
    fast = ColorSmoother(smoothing=5.0)  # clamped to 1.0
    fast.reset((0, 0, 0))
    fast.set_target((200, 200, 200))
    assert fast.advance() == (200, 200, 200)

    slow = ColorSmoother(smoothing=0.0)  # clamped up to a tiny positive value
    slow.reset((0, 0, 0))
    slow.set_target((255, 255, 255))
    step = slow.advance()
    assert 0 < step[0] < 255

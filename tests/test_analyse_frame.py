"""The offline frame analyser.

It exists so a "wrong colour" report can be answered with the algorithm's own
output instead of a photograph of a wall. The load-bearing test is the one that
reproduces the shape of that argument: a frame whose border is cool and whose
subject is warm.
"""

from __future__ import annotations

from tools.analyse_frame import analyse_buffer


def _frame(width: int, height: int, painter) -> bytes:
    """A BGRA buffer, as a screen grab produces."""
    buffer = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            r, g, b = painter(x, y)
            offset = (y * width + x) * 4
            buffer[offset] = b
            buffer[offset + 1] = g
            buffer[offset + 2] = r
            buffer[offset + 3] = 255
    return bytes(buffer)


def _cool_border_warm_centre(x: int, y: int) -> tuple[int, int, int]:
    if y >= 200:
        return (55, 60, 85)      # dark water along the bottom
    if 90 <= y < 190 and 100 <= x < 300:
        return (235, 150, 70)    # the sunset, in the middle
    return (110, 130, 190)       # sky everywhere else


def _rows(intensity: int = 55, smoothness: int = 65) -> dict[tuple[str, str], str]:
    frame = _frame(400, 300, _cool_border_warm_centre)
    return {
        (profile, region): final
        for profile, region, _raw, final in analyse_buffer(frame, 400, 300, intensity, smoothness)
    }


def _blueish(hex_colour: str) -> bool:
    r, b = int(hex_colour[1:3], 16), int(hex_colour[5:7], 16)
    return b > r


def test_the_region_decides_whether_this_frame_is_a_sky_or_a_sunset() -> None:
    """The whole point of the tool. Full screen honestly sees mostly sky and
    water; the centre sees the subject. Neither is a bug, and without the tool
    the difference is argued from a photograph."""
    rows = _rows()

    for profile in ("desktop", "game", "movie"):
        assert _blueish(rows[(profile, "full")]), f"{profile}/full should follow the border"
        assert not _blueish(rows[(profile, "center")]), f"{profile}/center should follow the subject"


def test_every_profile_and_region_is_covered() -> None:
    rows = _rows()
    assert len(rows) == 12


def test_a_stronger_boost_does_not_change_which_hue_wins() -> None:
    """Intensity decides how vivid, not what colour. If it flipped the hue, the
    slider would be a second colour control rather than a strength one."""
    calm = _rows(intensity=20)
    strong = _rows(intensity=90)

    for key, colour in calm.items():
        assert _blueish(colour) == _blueish(strong[key]), f"{key} changed hue with intensity"


def test_a_flat_grey_frame_is_left_grey() -> None:
    """The saturation floor must not invent a colour where there is no hue."""
    frame = _frame(120, 90, lambda x, y: (128, 128, 128))

    for _profile, _region, _raw, final in analyse_buffer(frame, 120, 90, 55, 65):
        r, g, b = (int(final[i : i + 2], 16) for i in (1, 3, 5))
        assert max(r, g, b) - min(r, g, b) <= 2, f"grey was tinted: {final}"

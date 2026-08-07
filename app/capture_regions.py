"""Which part of the screen feeds the strip, as fractions of the frame.

One definition, used by the capture loop and by the picture that explains it.
A widget that drew "roughly the middle" while the loop sampled a precise
quarter would teach the wrong thing about the app's own behaviour — and the
diagram would drift silently the first time either side was retuned.

Qt-free and keyed by stable ids, so a saved choice survives a language change.
"""

from __future__ import annotations

from dataclasses import dataclass

# This order is the order of the segments and of arrow-key travel, so top comes
# before bottom: on screen the bands are stacked that way, and a picker that
# walks them in the other order reads as a mistake.
REGION_IDS: tuple[str, ...] = ("full", "center", "top", "bottom")
DEFAULT_REGION = "full"

# The centre takes half of each side — a quarter of the area, not "the middle
# bit". Top and bottom take a third of the height. These numbers are the
# behaviour, so they live here rather than in either caller.
_CENTRE_SIDE = 0.5
_BAND_HEIGHT = 1.0 / 3.0


@dataclass(frozen=True)
class RegionBox:
    """A rectangle as fractions of the frame, 0..1 from the top-left."""

    left: float = 0.0
    top: float = 0.0
    width: float = 1.0
    height: float = 1.0


_BOXES: dict[str, RegionBox] = {
    "full": RegionBox(),
    "center": RegionBox(
        left=(1.0 - _CENTRE_SIDE) / 2.0,
        top=(1.0 - _CENTRE_SIDE) / 2.0,
        width=_CENTRE_SIDE,
        height=_CENTRE_SIDE,
    ),
    "top": RegionBox(height=_BAND_HEIGHT),
    "bottom": RegionBox(top=1.0 - _BAND_HEIGHT, height=_BAND_HEIGHT),
}


def normalize_region(region: object) -> str:
    """A known region id, or the default — never raises on stored junk."""
    key = str(region or "").strip().lower()
    return key if key in _BOXES else DEFAULT_REGION


def region_box(region: object) -> RegionBox:
    return _BOXES[normalize_region(region)]


def region_for_monitor(monitor: dict, region: object) -> dict:
    """The mss grab rectangle for one monitor, in absolute pixels.

    Rounded down, then floored at one pixel: a grab of zero height returns no
    bytes and the frame is lost rather than merely small.
    """
    left = int(monitor["left"])
    top = int(monitor["top"])
    width = int(monitor["width"])
    height = int(monitor["height"])
    box = region_box(region)
    return {
        "left": left + int(width * box.left),
        "top": top + int(height * box.top),
        "width": max(1, int(width * box.width)),
        "height": max(1, int(height * box.height)),
    }

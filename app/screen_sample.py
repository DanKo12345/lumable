"""Spatial analysis of one captured screen frame → one representative colour.

Qt-free and **stateless**: given a BGRA frame (as ``mss`` produces) plus its
dimensions and a :class:`SampleConfig`, it returns a single RGB. It never looks
at previous frames — the temporal side (smoothing, flash limiting) lives in
:mod:`app.screen_temporal`, so "what colour is in *this* frame" can be tested on
its own, and a jittery result can be diagnosed without replaying a stream.

Frame format (the contract the whole module is built on): ``mss`` buffers are
**BGRA, row-major, tightly packed**. The byte offset of pixel ``(x, y)`` is
``(y * width + x) * channels`` and the channels are ``B, G, R, A``.

The two ideas that make this look better than a whole-screen average:

- **Edge-weighted sampling.** A bias light usually sits behind the monitor, so
  the colours near the screen's border set the mood more than the middle does.
- **Black-bar rejection.** Letterboxed video (or pillarboxed 4:3) must not
  average its black bars into the result, which would drag everything to grey.

Optionally the colour is the **dominant** hue cluster rather than a blend, so a
mostly-grey screen with one strong colour reflects that colour instead of a
muddy mean.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

RGB = tuple[int, int, int]

# A row/column counts as part of a black bar only if it is this dark; and we
# never trim more than this fraction from a side, so a genuinely dark scene is
# not mistaken for one giant letterbox.
_BAR_LUMA_MAX = 22
_BAR_MAX_FRACTION = 0.45
# Hue buckets for dominant-colour extraction, plus one bin for near-grey pixels.
_HUE_BINS = 12


@dataclass(frozen=True)
class SampleConfig:
    """How a frame is reduced to one colour. All spatial, no history."""

    edge_weight: float = 1.6      # 0 = uniform; higher favours the border
    dominant: bool = True          # pick the strongest hue cluster vs blend all
    reject_black_bars: bool = True
    sample_step: int = 1           # sample every Nth pixel (caller sizes for speed)
    chroma_floor: int = 6          # keep near-grey frames from weighting to nothing


@dataclass(frozen=True)
class ActiveRect:
    left: int
    top: int
    right: int   # exclusive
    bottom: int  # exclusive

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


def _row_is_dark(buffer: bytes, y: int, width: int, channels: int, step: int) -> bool:
    base = y * width * channels
    total = 0
    count = 0
    x = 0
    while x < width:
        i = base + x * channels
        total += max(buffer[i], buffer[i + 1], buffer[i + 2])
        count += 1
        x += step
    return count > 0 and (total // count) <= _BAR_LUMA_MAX


def _col_is_dark(buffer: bytes, x: int, width: int, height: int, channels: int, step: int) -> bool:
    total = 0
    count = 0
    y = 0
    while y < height:
        i = (y * width + x) * channels
        total += max(buffer[i], buffer[i + 1], buffer[i + 2])
        count += 1
        y += step
    return count > 0 and (total // count) <= _BAR_LUMA_MAX


def sample_step_for(width: int, height: int, target_samples: int = 2500) -> int:
    """A 2-D grid step that yields roughly ``target_samples`` samples.

    Both x and y advance by the step here, so the sample count falls as the
    step *squared* — the old linear ``pixels // target`` (meant for a flat pass)
    would take a step of ~830 on Full HD and sample about six pixels. The square
    root keeps the grid near the target at any resolution.
    """
    pixels = max(1, int(width) * int(height))
    return max(1, round((pixels / max(1, target_samples)) ** 0.5))


def _scan_bar(is_dark, limit: int) -> int:
    """Depth of the dark bar at one edge, in rows/columns.

    Coarse-to-fine so a fully dark frame is bounded work: a naive per-line walk
    up to ``limit`` costs ~limit dark-line tests (≈40 ms on a black Full HD
    frame, all holding the GIL). Here a coarse stride finds the transition, then
    a short refine pins it — a few dozen tests per side regardless of content.
    """
    if limit <= 0 or not is_dark(0):
        return 0
    coarse = max(1, limit // 24)
    k = 0
    last_dark = 0
    while k < limit and is_dark(k):
        last_dark = k
        k += coarse
    edge = last_dark + 1
    end = min(k, limit)
    while edge < end and is_dark(edge):
        edge += 1
    return edge


def detect_active_rect(buffer: bytes, width: int, height: int, *, channels: int = 4) -> ActiveRect:
    """The rectangle left once near-black letterbox/pillarbox bars are trimmed.

    Trims from each side only while whole rows/columns are dark, capped so a dark
    scene never collapses to nothing. Returns the full frame when nothing is
    trimmed (the common case).
    """
    if width <= 0 or height <= 0 or len(buffer) < width * height * channels:
        return ActiveRect(0, 0, max(0, width), max(0, height))

    col_step = max(1, width // 64)
    row_step = max(1, height // 64)
    max_v = int(height * _BAR_MAX_FRACTION)
    max_h = int(width * _BAR_MAX_FRACTION)

    top = _scan_bar(lambda y: _row_is_dark(buffer, y, width, channels, col_step), max_v)
    bottom = height - _scan_bar(
        lambda y: _row_is_dark(buffer, height - 1 - y, width, channels, col_step), max_v
    )
    left = _scan_bar(lambda x: _col_is_dark(buffer, x, width, height, channels, row_step), max_h)
    right = width - _scan_bar(
        lambda x: _col_is_dark(buffer, width - 1 - x, width, height, channels, row_step), max_h
    )

    if right - left < width // 8 or bottom - top < height // 8:
        return ActiveRect(0, 0, width, height)  # trimmed too aggressively — trust nothing
    return ActiveRect(left, top, right, bottom)


def _edge_proximity(x: int, y: int, rect: ActiveRect) -> float:
    """1.0 at the active rect's border, → 0 toward its centre."""
    half_w = max(1.0, rect.width / 2.0)
    half_h = max(1.0, rect.height / 2.0)
    dx = min(x - rect.left, rect.right - 1 - x) / half_w
    dy = min(y - rect.top, rect.bottom - 1 - y) / half_h
    nearest = min(max(0.0, dx), max(0.0, dy))
    return max(0.0, 1.0 - nearest)


def extract_color(buffer: bytes, width: int, height: int, config: SampleConfig | None = None) -> RGB:
    """Reduce a BGRA frame to one representative RGB (see the module docstring)."""
    config = config or SampleConfig()
    channels = 4
    if width <= 0 or height <= 0 or len(buffer) < width * height * channels:
        return (0, 0, 0)

    rect = (
        detect_active_rect(buffer, width, height, channels=channels)
        if config.reject_black_bars
        else ActiveRect(0, 0, width, height)
    )
    step = max(1, config.sample_step)

    # Per-hue-bin accumulators (bin _HUE_BINS is the near-grey catch-all).
    bins_r = [0.0] * (_HUE_BINS + 1)
    bins_g = [0.0] * (_HUE_BINS + 1)
    bins_b = [0.0] * (_HUE_BINS + 1)
    bins_w = [0.0] * (_HUE_BINS + 1)
    plain_r = plain_g = plain_b = 0
    plain_count = 0

    y = rect.top
    while y < rect.bottom:
        row = y * width * channels
        x = rect.left
        while x < rect.right:
            i = row + x * channels
            b = buffer[i]
            g = buffer[i + 1]
            r = buffer[i + 2]
            plain_r += r
            plain_g += g
            plain_b += b
            plain_count += 1

            chroma = max(r, g, b) - min(r, g, b)
            edge = 1.0 + config.edge_weight * _edge_proximity(x, y, rect)
            weight = (chroma + config.chroma_floor) * edge

            if chroma <= config.chroma_floor:
                bucket = _HUE_BINS
            else:
                hue, _s, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                bucket = min(_HUE_BINS - 1, int(hue * _HUE_BINS))
            bins_r[bucket] += r * weight
            bins_g[bucket] += g * weight
            bins_b[bucket] += b * weight
            bins_w[bucket] += weight
            x += step
        y += step

    if plain_count == 0:
        return (0, 0, 0)

    if config.dominant:
        # Heaviest *chromatic* bucket wins; the grey catch-all only wins if the
        # frame really has no colour to speak of.
        best = max(range(_HUE_BINS), key=lambda k: bins_w[k])
        if bins_w[best] > 0 and bins_w[best] >= bins_w[_HUE_BINS] * 0.5:
            w = bins_w[best]
            return (round(bins_r[best] / w), round(bins_g[best] / w), round(bins_b[best] / w))

    total_w = sum(bins_w)
    if total_w > 0:
        return (
            round(sum(bins_r) / total_w),
            round(sum(bins_g) / total_w),
            round(sum(bins_b) / total_w),
        )
    return (plain_r // plain_count, plain_g // plain_count, plain_b // plain_count)

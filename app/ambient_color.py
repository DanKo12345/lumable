from __future__ import annotations

import colorsys

RGB = tuple[int, int, int]


def average_color(buffer: bytes, *, channels: int = 4, sample_step: int = 1) -> RGB:
    """Saturation-weighted average colour of a raw pixel buffer.

    A plain mean of a busy screen collapses toward grey/white, which makes the strip
    look permanently washed out. Weighting each pixel by its chroma (how colourful it
    is) lets vivid regions drive the result while large flat grey/white areas barely
    count, so the strip reflects the screen's actual mood. A fully grey frame has no
    chroma to weight by, so it falls back to the plain mean.

    Defaults assume the BGRA layout produced by ``mss`` screen grabs. ``sample_step``
    skips pixels for speed (e.g. 4 = sample every 4th pixel), which is plenty for an
    ambient average and keeps capture cheap.
    """
    step = max(1, channels * max(1, sample_step))
    length = len(buffer)
    weighted_r = weighted_g = weighted_b = 0
    weight_sum = 0
    total_r = total_g = total_b = 0
    count = 0
    index = 0
    while index + channels <= length:
        b = buffer[index]
        g = buffer[index + 1]
        r = buffer[index + 2]
        total_r += r
        total_g += g
        total_b += b
        count += 1
        # Chroma: 0 for grey/white/black, up to 255 for a fully vivid pixel.
        weight = max(r, g, b) - min(r, g, b)
        if weight:
            weighted_r += r * weight
            weighted_g += g * weight
            weighted_b += b * weight
            weight_sum += weight
        index += step
    if count == 0:
        return (0, 0, 0)
    if weight_sum > 0:
        return (weighted_r // weight_sum, weighted_g // weight_sum, weighted_b // weight_sum)
    return (total_r // count, total_g // count, total_b // count)


def shape_color(
    rgb: RGB,
    *,
    saturation: float = 1.4,
    gamma: float = 1.0,
    min_brightness: int = 0,
    max_brightness: int = 255,
) -> RGB:
    """Make an averaged screen colour look good on a LED strip.

    Screen averages are usually washed out, so we boost saturation; gamma lifts the
    mid-tones; and the brightness range keeps the strip from going fully black or
    blinding. All shaping is done in HSV so the hue is preserved.
    """
    r = max(0, min(255, int(rgb[0])))
    g = max(0, min(255, int(rgb[1])))
    b = max(0, min(255, int(rgb[2])))
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

    s = max(0.0, min(1.0, s * max(0.0, saturation)))
    if gamma > 0.0 and gamma != 1.0:
        v = v ** (1.0 / gamma)

    lo = max(0, min(255, int(min_brightness))) / 255.0
    hi = max(0, min(255, int(max_brightness))) / 255.0
    if hi < lo:
        lo, hi = hi, lo
    v = lo + max(0.0, min(1.0, v)) * (hi - lo)

    rr, gg, bb = colorsys.hsv_to_rgb(h, s, max(0.0, min(1.0, v)))
    return (round(rr * 255), round(gg * 255), round(bb * 255))

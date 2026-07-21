from __future__ import annotations

import colorsys

RGB = tuple[int, int, int]

# Saturation enhancement is gated so a near-grey colour is left untouched. Both
# gates are smooth ramps (not hard thresholds): a hard edge would make a
# one-level input change flip a strong profile between "no boost" and "full
# boost", which itself jitters near the boundary. The gate is judged on the
# ORIGINAL colour via two signals — either one closing the gate means "grey":
# tiny HSV saturation (light near-greys) and tiny absolute chroma (dark
# near-greys like (5,3,3) whose HSV saturation is formally high).
_SAT_DEAD_ZONE = 0.06
_SAT_RAMP = 0.12
_CHROMA_DEAD = 8    # max(rgb) - min(rgb), 0..255
_CHROMA_RAMP = 8


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 <= edge0:
        return 0.0 if x < edge0 else 1.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


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
    min_saturation: float = 0.0,
) -> RGB:
    """Make an averaged screen colour look good on a LED strip.

    Screen averages are usually washed out, so we boost saturation; gamma lifts the
    mid-tones; and the brightness range keeps the strip from going fully black or
    blinding. ``min_saturation`` is a floor that pulls a barely-tinted colour up to
    a clearly visible one — but only when there is a hue to work with, so a truly
    grey frame stays grey instead of being tinted an arbitrary colour. All shaping
    is done in HSV so the hue is preserved.
    """
    r = max(0, min(255, int(rgb[0])))
    g = max(0, min(255, int(rgb[1])))
    b = max(0, min(255, int(rgb[2])))
    chroma = max(r, g, b) - min(r, g, b)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

    # Gate ALL saturation enhancement — the boost *and* the floor — on the
    # ORIGINAL colour: a strong per-profile boost applied to sensor/JPEG noise is
    # itself what colours a grey screen, so near-grey pixels must be left
    # untouched entirely, not just spared the floor. Both gates ramp smoothly and
    # combine by ``min`` (either can close), so a one-level input change never
    # snaps between no enhancement and full enhancement.
    raw_s = s
    gate = min(
        _smoothstep(_SAT_DEAD_ZONE, _SAT_DEAD_ZONE + _SAT_RAMP, raw_s),
        _smoothstep(_CHROMA_DEAD, _CHROMA_DEAD + _CHROMA_RAMP, chroma),
    )
    if gate > 0.0:
        boosted = max(0.0, min(1.0, raw_s * max(0.0, saturation)))
        floor = max(0.0, min(1.0, min_saturation))
        target_s = max(boosted, floor)
        s = raw_s + (target_s - raw_s) * gate

    if gamma > 0.0 and gamma != 1.0:
        v = v ** (1.0 / gamma)

    lo = max(0, min(255, int(min_brightness))) / 255.0
    hi = max(0, min(255, int(max_brightness))) / 255.0
    if hi < lo:
        lo, hi = hi, lo
    v = lo + max(0.0, min(1.0, v)) * (hi - lo)

    rr, gg, bb = colorsys.hsv_to_rgb(h, s, max(0.0, min(1.0, v)))
    return (round(rr * 255), round(gg * 255), round(bb * 255))

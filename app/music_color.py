from __future__ import annotations

RGB = tuple[int, int, int]

# Default colour per band — a soft coral -> violet -> cyan palette that blends
# smoothly as the music shifts, instead of harsh pure red/green/blue jumps.
DEFAULT_BAND_COLORS: tuple[RGB, RGB, RGB] = ((255, 80, 70), (180, 90, 255), (60, 190, 255))


def _clamp8(value: float) -> int:
    return max(0, min(255, round(value)))


def normalize_level(rms: float, *, noise_floor: float = 0.0025, ceiling: float = 0.25) -> float:
    """Map a raw RMS amplitude to a perceptual 0..1 loudness level.

    Pure (no numpy) so it can be unit-tested. ``rms`` is the root-mean-square of
    the audio block (roughly 0..1). Below ``noise_floor`` the result is 0
    (treated as silence); at/above ``ceiling`` it saturates at 1. A square-root
    curve keeps quiet passages visible without loud ones clipping everything.
    """
    if rms <= noise_floor:
        return 0.0
    span = max(1e-6, ceiling - noise_floor)
    linear = min(1.0, (rms - noise_floor) / span)
    return linear**0.5


def bands_to_rgb(
    bass: float,
    mid: float,
    treble: float,
    level: float,
    *,
    colors: tuple[RGB, RGB, RGB] | None = None,
    saturation: float = 1.0,
    floor_brightness: float = 0.06,
) -> RGB:
    """Map three band energies (>=0) and an overall level (0..1) to an RGB colour.

    Each band contributes its own colour (``colors`` = bass, mid, treble), blended
    by how strong that band is, then re-normalised so the result stays vivid. With
    the default red/green/blue this reduces to "loudest band sets the hue". The
    overall ``level`` sets brightness, with a small ``floor_brightness`` so the
    strip glows softly between beats instead of blinking fully off. ``saturation``
    above 1.0 deepens the dominant hue. Pure and clamped, so it's safe to unit-test.
    """
    bass = max(0.0, bass)
    mid = max(0.0, mid)
    treble = max(0.0, treble)
    color_bass, color_mid, color_treble = colors if colors is not None else DEFAULT_BAND_COLORS

    peak = max(bass, mid, treble, 1e-6)
    weight_bass, weight_mid, weight_treble = bass / peak, mid / peak, treble / peak
    r = weight_bass * color_bass[0] + weight_mid * color_mid[0] + weight_treble * color_treble[0]
    g = weight_bass * color_bass[1] + weight_mid * color_mid[1] + weight_treble * color_treble[1]
    b = weight_bass * color_bass[2] + weight_mid * color_mid[2] + weight_treble * color_treble[2]

    # Re-normalise so the brightest channel can reach full intensity (keeps the
    # hue saturated regardless of how dark the chosen band colours are).
    channel_peak = max(r, g, b, 1e-6)
    r, g, b = r / channel_peak, g / channel_peak, b / channel_peak

    if saturation != 1.0:
        average = (r + g + b) / 3.0
        r = average + (r - average) * saturation
        g = average + (g - average) * saturation
        b = average + (b - average) * saturation

    level = max(0.0, min(1.0, level))
    brightness = floor_brightness + (1.0 - floor_brightness) * level
    return (
        _clamp8(r * 255 * brightness),
        _clamp8(g * 255 * brightness),
        _clamp8(b * 255 * brightness),
    )

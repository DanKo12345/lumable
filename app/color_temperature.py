from __future__ import annotations

import math

# Cheap RGB controllers (BLEDOM/Triones/…) have no dedicated white channel, so a
# "colour temperature" control is emulated by driving R/G/B to the colour of a
# black-body radiator at the chosen Kelvin. The curve below is the widely used
# Tanner Helland approximation, which is accurate enough for a warm↔cool slider.

MIN_KELVIN = 1000
MAX_KELVIN = 12000
# A sensible default range for the UI slider (warm incandescent → cool daylight).
WARM_KELVIN = 2000
NEUTRAL_KELVIN = 4500
COOL_KELVIN = 6500


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cct_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Convert a colour temperature in Kelvin to an approximate sRGB triplet.

    Input is clamped to [MIN_KELVIN, MAX_KELVIN]. Output channels are ints 0-255.
    """
    kelvin = int(_clamp(float(kelvin), MIN_KELVIN, MAX_KELVIN))
    temp = kelvin / 100.0

    if temp <= 66:
        red = 255.0
    else:
        red = 329.698727446 * ((temp - 60.0) ** -0.1332047592)

    if temp <= 66:
        green = 99.4708025861 * math.log(temp) - 161.1195681661
    else:
        green = 288.1221695283 * ((temp - 60.0) ** -0.0755148492)

    if temp >= 66:
        blue = 255.0
    elif temp <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(temp - 10.0) - 305.0447927307

    return (
        round(_clamp(red, 0.0, 255.0)),
        round(_clamp(green, 0.0, 255.0)),
        round(_clamp(blue, 0.0, 255.0)),
    )

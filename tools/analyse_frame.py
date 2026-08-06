"""What the strip would show for a given image, on every profile and region.

A "wrong colour" report is otherwise argued from a photograph of a wall. Point
this at the frame that looked wrong and it prints the answer for all twelve
combinations, so the question becomes which setting was active rather than
whether the algorithm is broken.

    python tools/analyse_frame.py shot.png
    python tools/analyse_frame.py shot.png --intensity 80 --smoothness 40

Colours are the per-frame result: sampling and shaping, without the temporal
filter, which only decides how fast the strip travels toward this value.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

if __name__ == "__main__":  # running as a script: make the package importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ambient_color import shape_color
from app.ambient_controller import _region_for
from app.screen_profiles import (
    NEUTRAL_INTENSITY,
    NEUTRAL_SMOOTHNESS,
    PROFILE_IDS,
    get_profile,
    resolve_configs,
)
from app.screen_sample import extract_color, sample_step_for

REGIONS = ("full", "center", "bottom", "top")


def _load_bgra(path: Path) -> tuple[bytes, int, int]:
    """The image as the BGRA buffer a screen grab produces."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "Pillow is required to read images: pip install pillow"
        ) from None
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        pixels = rgb.tobytes()
    buffer = bytearray(width * height * 4)
    for index in range(width * height):
        r, g, b = pixels[index * 3 : index * 3 + 3]
        offset = index * 4
        buffer[offset] = b
        buffer[offset + 1] = g
        buffer[offset + 2] = r
        buffer[offset + 3] = 255
    return bytes(buffer), width, height


def _crop(buffer: bytes, width: int, height: int, region: str) -> tuple[bytes, int, int]:
    """The same crop the capture loop asks the screen for."""
    box = _region_for({"left": 0, "top": 0, "width": width, "height": height}, region)
    left, top = int(box["left"]), int(box["top"])
    box_w, box_h = int(box["width"]), int(box["height"])
    rows = []
    for y in range(top, top + box_h):
        start = (y * width + left) * 4
        rows.append(buffer[start : start + box_w * 4])
    return b"".join(rows), box_w, box_h


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def analyse(path: Path, intensity: int, smoothness: int) -> list[tuple[str, str, str, str]]:
    buffer, width, height = _load_bgra(path)
    return analyse_buffer(buffer, width, height, intensity, smoothness)


def analyse_buffer(
    buffer: bytes, width: int, height: int, intensity: int, smoothness: int
) -> list[tuple[str, str, str, str]]:
    """Every profile and region for one BGRA frame.

    Split from the file loading so the pipeline can be exercised without an
    image library — the answer must not depend on how the pixels arrived.
    """
    rows: list[tuple[str, str, str, str]] = []
    for profile_id in PROFILE_IDS:
        for region in REGIONS:
            cropped, crop_w, crop_h = _crop(buffer, width, height, region)
            resolved = resolve_configs(get_profile(profile_id), intensity, smoothness)
            sample = replace(
                resolved.sample, sample_step=sample_step_for(crop_w, crop_h)
            )
            raw = extract_color(cropped, crop_w, crop_h, sample)
            final = shape_color(
                raw,
                saturation=resolved.shape.saturation,
                gamma=resolved.shape.gamma,
                min_brightness=resolved.shape.min_brightness,
                max_brightness=resolved.shape.max_brightness,
                min_saturation=resolved.shape.min_saturation,
            )
            rows.append((profile_id, region, _hex(raw), _hex(final)))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("--intensity", type=int, default=NEUTRAL_INTENSITY)
    parser.add_argument("--smoothness", type=int, default=NEUTRAL_SMOOTHNESS)
    args = parser.parse_args()

    if not args.image.exists():
        print(f"no such file: {args.image}", file=sys.stderr)
        return 1

    rows = analyse(args.image, args.intensity, args.smoothness)
    print(f"{args.image.name}  intensity {args.intensity}  smoothness {args.smoothness}")
    print(f"{'profile':<9} {'region':<8} {'raw':<9} final")
    for profile_id, region, raw, final in rows:
        print(f"{profile_id:<9} {region:<8} {raw:<9} {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the compact 0.3.7 before/after GIF from real LumaBLE card captures."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
OUTPUT = IMAGES / "release-0.3.7-before-after.gif"

CANVAS = (1080, 800)
VIEWPORT_WIDTH = 1016
BACKGROUND = (10, 12, 19)
TEXT = (242, 245, 252)
MUTED = (159, 168, 188)
ACCENT = (119, 174, 255)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def _fit_width(image: Image.Image) -> Image.Image:
    copy = image.convert("RGB")
    height = round(copy.height * VIEWPORT_WIDTH / copy.width)
    return copy.resize((VIEWPORT_WIDTH, height), Image.Resampling.LANCZOS)


def _ease(value: float) -> float:
    return 0.5 - math.cos(value * math.pi) / 2.0


def _base(title: str) -> Image.Image:
    frame = Image.new("RGB", CANVAS, BACKGROUND)
    draw = ImageDraw.Draw(frame)
    draw.text((32, 24), title, fill=TEXT, font=_font(28, bold=True))
    draw.text((32, 62), "BEFORE · 0.3.6", fill=MUTED, font=_font(15, bold=True))
    right = "AFTER · 0.3.7"
    font = _font(15, bold=True)
    box = draw.textbbox((0, 0), right, font=font)
    draw.text((CANVAS[0] - 32 - (box[2] - box[0]), 62), right, fill=ACCENT, font=font)
    return frame


def _stage(title: str, before_path: Path, after_path: Path) -> list[Image.Image]:
    before = _fit_width(Image.open(before_path))
    after = _fit_width(Image.open(after_path))
    origin = ((CANVAS[0] - VIEWPORT_WIDTH) // 2, 112)

    frames: list[Image.Image] = []
    positions = [0.0] * 8 + [_ease(index / 19) for index in range(20)] + [1.0] * 12
    for progress in positions:
        frame = _base(title)
        before_xy = origin
        after_xy = origin
        frame.paste(before, before_xy)

        reveal = round(after.width * progress)
        if reveal:
            frame.paste(after.crop((0, 0, reveal, after.height)), after_xy)

        line_x = after_xy[0] + reveal
        if 0 < reveal < after.width:
            glow = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            glow_draw.line(
                (line_x, after_xy[1], line_x, after_xy[1] + after.height),
                fill=(*ACCENT, 180),
                width=9,
            )
            glow = glow.filter(ImageFilter.GaussianBlur(6))
            frame = Image.alpha_composite(frame.convert("RGBA"), glow).convert("RGB")
            draw = ImageDraw.Draw(frame)
            draw.line(
                (line_x, after_xy[1], line_x, after_xy[1] + after.height),
                fill=TEXT,
                width=2,
            )
            centre_y = after_xy[1] + after.height // 2
            draw.ellipse(
                (line_x - 15, centre_y - 15, line_x + 15, centre_y + 15),
                fill=TEXT,
                outline=ACCENT,
                width=3,
            )
            draw.polygon(
                ((line_x - 7, centre_y), (line_x - 2, centre_y - 5), (line_x - 2, centre_y + 5)),
                fill=ACCENT,
            )
            draw.polygon(
                ((line_x + 7, centre_y), (line_x + 2, centre_y - 5), (line_x + 2, centre_y + 5)),
                fill=ACCENT,
            )
        frames.append(frame)
    return frames


def main() -> int:
    diagnostics = _stage(
        "Diagnostics",
        IMAGES / "release-0.3.7-diagnostics-before.png",
        IMAGES / "release-0.3.7-diagnostics-after.png",
    )
    diy = _stage(
        "DIY effects",
        IMAGES / "release-0.3.7-diy-before.png",
        IMAGES / "release-0.3.7-diy-after.png",
    )

    blank = Image.new("RGB", CANVAS, BACKGROUND)
    fade_out = [Image.blend(diagnostics[-1], blank, index / 6.0) for index in range(1, 6)]
    fade_in = [Image.blend(blank, diy[0], index / 6.0) for index in range(1, 6)]
    frames = diagnostics + fade_out + [blank] * 3 + fade_in + diy

    palette_source = Image.new("RGB", (CANVAS[0] * 2, CANVAS[1] * 2), BACKGROUND)
    for index, frame in enumerate((diagnostics[0], diagnostics[-1], diy[0], diy[-1])):
        palette_source.paste(frame, ((index % 2) * CANVAS[0], (index // 2) * CANVAS[1]))
    palette = palette_source.convert("P", palette=Image.Palette.ADAPTIVE, colors=224)
    encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    encoded[0].save(
        OUTPUT,
        save_all=True,
        append_images=encoded[1:],
        duration=100,
        loop=0,
        optimize=False,
        disposal=1,
    )
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

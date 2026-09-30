#!/usr/bin/env python3
"""Crop the mausoleum and the farmer's lantern from a 1x frame and a 1.5x frame,
scale the 1x crop up by 1.5, and stack them so the two can be compared by eye.

Everything in this game is placed in logical points, and a 3/2 frame is the 1x
frame with a 1.5x viewport, so a correctly-attached sprite must land in exactly
the same place in both crops. A sprite that is off by a fixed screen-space
offset shows up immediately.

Usage: python _analysis/_emitter_crop.py A.png B.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

# (name, centre_x, centre_y, half_w, half_h) in LOGICAL points of the 1x frame.
REGIONS = [
    ("mausoleum", 566, 700, 70, 60),
    ("lantern", 462, 233, 60, 55),
]


def main() -> int:
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    scale = b.width / a.width
    print(f"A {a_path.name} {a.size}   B {b_path.name} {b.size}   scale {scale:.3f}")

    for name, cx, cy, hw, hh in REGIONS:
        # Crop A (native) and magnify it, exactly like the emulator's viewport does.
        a_box = (cx - hw, cy - hh, cx + hw, cy + hh)
        a_crop = a.crop(a_box)
        a_mag = a_crop.resize(
            (int(a_crop.width * scale), int(a_crop.height * scale)), Image.NEAREST
        )
        # Crop B at the corresponding PLACE. B's pixels are logical * scale, so
        # the same logical box is a_box * scale in B. Comparing these two crops
        # compares the same region of the world.
        b_box = tuple(int(round(v * scale)) for v in a_box)
        b_crop = b.crop(b_box).resize(a_mag.size, Image.NEAREST)

        w, h = a_mag.size
        canvas = Image.new("RGB", (w * 2 + 12, h + 20), (24, 24, 24))
        canvas.paste(a_mag, (0, 20))
        canvas.paste(b_crop, (w + 12, 20))
        d = ImageDraw.Draw(canvas)
        d.text((2, 4), f"{name}: A(x1) magnified 1.5x", fill=(255, 255, 0))
        d.text((w + 14, 4), f"{name}: B(x1.5) as rendered", fill=(0, 255, 255))
        # Centre crosshair on both halves.
        for ox in (0, w + 12):
            d.line((ox + w // 2, 20, ox + w // 2, 20 + h), fill=(255, 0, 255))
            d.line((ox, 20 + h // 2, ox + w, 20 + h // 2), fill=(255, 0, 255))

        out = Path(f"_analysis/perf/emitter_{name}_ab.png")
        canvas.save(out)

        # Numeric check on the same crop: mean absolute difference.
        da = np.asarray(a_mag, dtype=np.int16)
        db = np.asarray(b_crop, dtype=np.int16)
        diff = np.abs(da - db).max(axis=2)
        print(
            f"  {name:<10} crop {w}x{h}  meanerr {diff.mean():6.2f}  "
            f"px>32: {(diff > 32).mean() * 100:5.2f}%   -> {out}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

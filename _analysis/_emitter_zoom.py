#!/usr/bin/env python3
"""Blow up the two emitters the user named, side by side, so the difference
between "magnified" and "wrong" is visible rather than inferred.

Left: the native frame, nearest-neighbour magnified by the same factor the
emulator uses. Right: the frame actually rendered at that scale. Both crops
cover the same region of the world. Any difference is real.

Usage: python _analysis/_emitter_zoom.py A.png B.png name:cx:cy:hw:hh [...]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

ZOOM = 6


def main() -> int:
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    regions = []
    for spec in sys.argv[3:]:
        name, cx, cy, hw, hh = spec.split(":")
        regions.append((name, int(cx), int(cy), int(hw), int(hh)))
    if not regions:
        print(__doc__)
        return 2

    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    scale = b.width / a.width
    print(f"A {a_path.name} {a.size}  B {b_path.name} {b.size}  scale {scale:.3f}")

    for name, cx, cy, hw, hh in regions:
        abox = (cx - hw, cy - hh, cx + hw, cy + hh)
        a_crop = a.crop(abox)
        a_mag = a_crop.resize(
            (a_crop.width * ZOOM * 2 // 2, a_crop.height * ZOOM), Image.NEAREST
        )
        bbox = tuple(int(round(v * scale)) for v in abox)
        b_crop = b.crop(bbox)
        # Magnify B by the same total factor so the two halves show the same
        # amount of the world at the same on-screen size.
        b_mag = b_crop.resize(a_mag.size, Image.NEAREST)

        w, h = a_mag.size
        canvas = Image.new("RGB", (w * 2 + 16, h + 22), (20, 20, 20))
        canvas.paste(a_mag, (0, 22))
        canvas.paste(b_mag, (w + 16, 22))
        d = ImageDraw.Draw(canvas)
        d.text((3, 6), f"{name}: native x1, magnified {ZOOM}x", fill=(255, 230, 0))
        d.text((w + 19, 6), f"{name}: rendered at scale {scale:.2f}", fill=(0, 240, 255))
        out = Path(f"_analysis/perf/zoom6_{name}.png")
        canvas.save(out)
        print(f"  {name}: logical box {abox} -> {out}  ({w}x{h} per half)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

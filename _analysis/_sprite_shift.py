#!/usr/bin/env python3
"""Measure how far the emissive sprites move relative to the scene.

A 3/2 frame should be the 1x frame magnified by exactly 1.5 with no relative
motion of anything. So for every region of the world, the offset that best
aligns the native crop (magnified 1.5x) with the 3/2 crop should be (0, 0). If
the glow needs a different offset from the structure around it, the glow is
displaced relative to the world - which is exactly what the user describes.

Offsets are searched in whole output pixels and reported both in output pixels
and in logical points (divide by the scale), because a constant pixel offset and
a constant *logical* offset mean very different bugs.

Usage: python _analysis/_sprite_shift.py A.png B.png [region ...]
  region := name:cx:cy:halfw:halfh   (logical points in the native frame)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

DEFAULT_REGIONS = [
    # the two emitters the user named, plus reference structure
    ("mausoleum_door", 566, 700, 34, 34),
    ("lantern_hand", 462, 236, 22, 22),
    ("farmer_body", 462, 250, 26, 30),
    ("hedge_left", 120, 407, 40, 40),
    ("plot_centre", 420, 300, 40, 40),
    ("tractor", 180, 690, 40, 30),
]

RADIUS = 6  # search radius, in output pixels


def load(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)


def best_shift(a: np.ndarray, b: np.ndarray) -> tuple[tuple[int, int], float]:
    """Integer (dx, dy) minimising mean |a - shift(b)| over the search window.

    a and b must be the same shape. b is sampled with its centre displaced by
    (dx, dy), so a positive dx means the content of b sits dx pixels to the
    right of where a says it should be.
    """
    h, w = a.shape[:2]
    margin = RADIUS
    core_a = a[margin : h - margin, margin : w - margin]
    best = ((0, 0), float("inf"))
    for dy in range(-RADIUS, RADIUS + 1):
        for dx in range(-RADIUS, RADIUS + 1):
            core_b = b[margin + dy : h - margin + dy, margin + dx : w - margin + dx]
            err = float(np.abs(core_a - core_b).mean())
            if err < best[1]:
                best = ((dx, dy), err)
    return best


def main() -> int:
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    regions = DEFAULT_REGIONS
    if len(sys.argv) > 3:
        regions = []
        for spec in sys.argv[3:]:
            name, cx, cy, hw, hh = spec.split(":")
            regions.append((name, int(cx), int(cy), int(hw), int(hh)))

    a_img = Image.open(a_path).convert("RGB")
    b_img = Image.open(b_path).convert("RGB")
    scale = b_img.width / a_img.width
    a = load(a_path)
    b = load(b_path)
    print(f"A {a_path.name} {a.shape[1]}x{a.shape[0]}")
    print(f"B {b_path.name} {b.shape[1]}x{b.shape[0]}  scale {scale:.4f}")
    print(f"search radius {RADIUS} px; dy positive = B content sits LOWER\n")
    print(f"{'region':<16}{'shift px':>12}{'shift logical':>16}{'residual':>11}")
    for name, cx, cy, hw, hh in regions:
        abox = (cx - hw, cy - hh, cx + hw, cy + hh)
        a_crop = a_img.crop(abox)
        a_mag = np.asarray(
            a_crop.resize(
                (int(round(a_crop.width * scale)), int(round(a_crop.height * scale))),
                Image.NEAREST,
            ),
            dtype=np.float32,
        )
        bbox = tuple(int(round(v * scale)) for v in abox)
        b_crop = b_img.crop(bbox).resize(a_crop.size, Image.NEAREST)
        b_crop = np.asarray(
            b_crop.resize((a_mag.shape[1], a_mag.shape[0]), Image.NEAREST),
            dtype=np.float32,
        )
        (dx, dy), err = best_shift(a_mag, b_crop)
        print(
            f"{name:<16}{f'({dx:+d},{dy:+d})':>12}"
            f"{f'({dx/scale:+.2f},{dy/scale:+.2f})':>16}{err:>11.2f}"
        )
    print(
        "\nA glow that 'floats' shows a shift (dx, dy) clearly different from the\n"
        "structure in the same shot. Equal shifts everywhere mean the frame is a\n"
        "faithful magnification and the artefact is not positional."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

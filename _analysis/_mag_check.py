#!/usr/bin/env python3
"""Is the 3/2 frame a pure magnification of the native frame?

If yes, every sprite - glow included - is placed by the identical guest math and
merely magnified, so a "floating light" cannot come from the layout; it would
have to come from something resolution-dependent (filtering, sub-pixel
rounding, a render-to-texture pass). If no, the frame differs structurally and
the diff image shows exactly which part of the scene moved.

Usage: python _analysis/_mag_check.py A.png B.png [out_prefix]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def load(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)


def main() -> int:
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    prefix = sys.argv[3] if len(sys.argv) > 3 else "_mag"
    a, b = load(a_path), load(b_path)
    print(f"A {a_path.name} {a.shape[1]}x{a.shape[0]}")
    print(f"B {b_path.name} {b.shape[1]}x{b.shape[0]}")

    if b.shape[0] != a.shape[0]:
        # Resample A up to B with the same filter the GPU most closely
        # resembles (bilinear), then compare pixel for pixel.
        up = np.asarray(
            Image.fromarray(a.astype(np.uint8)).resize(
                (b.shape[1], b.shape[0]), Image.BILINEAR
            ),
            dtype=np.float32,
        )
    else:
        up = a

    diff = np.abs(up - b)
    print(f"bilinear-upscaled A vs B: mean {diff.mean():.3f}  max {diff.max():.0f}")
    for t in (8, 16, 32, 64):
        frac = (diff.max(axis=2) > t).mean()
        print(f"  pixels with any-channel delta > {t:>2}: {frac * 100:6.3f}%")

    # Where, if anywhere, did it change? Coarse 16x16 block map of the mean
    # error, so a structural difference (a sprite in the wrong place) shows up
    # as a hot block rather than a uniform haze.
    h, w = diff.shape[:2]
    bh, bw = 16, 16
    hm, wm = h // bh, w // bw
    blocks = diff[: hm * bh, : wm * bw].max(axis=2).reshape(hm, bh, wm, bw).mean(axis=(1, 3))
    hot = np.dstack(np.unravel_index(np.argsort(blocks.ravel())[::-1][:8], blocks.shape))[0]
    print("hottest blocks (row, col) of a %dx%d grid, block size %dx%d:" % (hm, wm, bw, bh))
    for r, c in hot:
        print(f"  block({r:>2},{c:>2})  x={c*bw:>4}..{(c+1)*bw:<4} y={r*bh:>4}..{(r+1)*bh:<4}  meanerr={blocks[r, c]:7.2f}")

    # Save a visual diff (amplified 4x) for eyeballing.
    vis = np.clip(diff * 4.0, 0, 255).astype(np.uint8)
    out = Path(prefix + "_diff.png")
    Image.fromarray(vis).save(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

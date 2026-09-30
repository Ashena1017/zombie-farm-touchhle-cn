#!/usr/bin/env python3
"""Does ZFR ever ask OpenGL for GL_VIEWPORT (0x0BA2)?

touchHLE's scale-hack implementation scales glViewport on the way out and
unscales the renderbuffer size on the way back. That is a consistent pair only
as long as the app never asks GL how big its viewport is: glGetIntegerv() falls
through to the host, so GL_VIEWPORT would report the SCALED rectangle while
every other size the app can see is unscaled. A light drawn from a
viewport-derived rectangle would then drift as --scale-hack changes.

So: find every machine-code materialisation of the constant 0x0BA2, in any
encoding (Thumb movw, literal pool, __const), and report where it lives.

Usage: python _analysis/_viewport_const_scan.py
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from annot_disasm import method_index  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"

# (name, value) for every pname whose guest-visible value touchHLE rewrites or
# could plausibly confuse. 0x0BA2 == GL_VIEWPORT.
CONSTS = [
    ("GL_VIEWPORT", 0x0BA2),
    ("GL_SCISSOR_BOX", 0x0C10),
    ("GL_MAX_VIEWPORT_DIMS", 0x0D3A),
    ("GL_RENDERBUFFER_WIDTH_OES", 0x8D42),
    ("GL_RENDERBUFFER_HEIGHT_OES", 0x8D43),
    ("GL_RENDERBUFFER_BINDING_OES", 0x8CA7),
    ("GL_FRAMEBUFFER_BINDING_OES", 0x8CA6),
]


def main() -> int:
    with zipfile.ZipFile(IPA) as z:
        fat = z.read("Payload/ZFR.app/ZFR")
    sl = next(s for s in parse_fat(fat) if s.subtype == 9)
    data = sl.data
    idx = method_index(sl)
    starts = sorted(idx)

    def owner(addr: int) -> str:
        prev = max((x for x in starts if x <= addr), default=None)
        if prev is None or addr - prev >= 0x2000:
            return "(no method)"
        n, s, _k = idx[prev]
        return f"{n} {s} +{addr - prev:#x}"

    for name, value in CONSTS:
        print(f"===== {name} = {value:#06x} =====")
        found = 0

        # 1) any 4-byte aligned word equal to the constant (literal pools,
        #    __const, jump tables).
        pat = struct.pack("<I", value)
        pos = 0
        words = []
        while True:
            i = data.find(pat, pos)
            if i < 0:
                break
            pos = i + 1
            if i % 4 == 0:
                words.append(i)
        if words:
            print(f"  raw 32-bit words ({len(words)}): " + ", ".join(hex(w) for w in words[:8]))
            found += len(words)

        # 2) Thumb-2 MOVW of the constant, e.g. `movw r1, #0xba2`.
        #    hw1 = 11110 i 10 0100 imm4 ; hw2 = 0 imm3 Rd imm8
        imm4 = (value >> 12) & 0xF
        i_bit = (value >> 11) & 1
        imm3 = (value >> 8) & 0x7
        imm8 = value & 0xFF
        hw1 = 0xF240 | (i_bit << 10) | imm4
        movws = []
        for rd in range(16):
            hw2 = (imm3 << 12) | (rd << 8) | imm8
            enc = struct.pack("<HH", hw1, hw2)
            p = 0
            while True:
                j = data.find(enc, p)
                if j < 0:
                    break
                p = j + 1
                # MOVW is 4-byte aligned in Thumb-2 code.
                if j % 4 == 0:
                    movws.append((j, rd))
        if movws:
            print(f"  Thumb MOVW sites ({len(movws)}):")
            for off, rd in movws[:12]:
                print(f"    file {off:#08x}  r{rd}   {owner(off)}")
            found += len(movws)

        if not found:
            print("  no materialisation found -> app never uses this constant")
        print()

    # Sanity check on the scanner itself: GL_VIEWPORT's neighbour 0x0BA1 is not
    # used by the app as far as we know, while selectors we *know* it calls
    # should show up. A scanner that finds nothing at all is not evidence.
    print("=== scanner sanity: does it find a constant we KNOW is used? ===")
    for name, value, expect in [("GL_TRIANGLE_STRIP(0x0005)", 0x0005, True)]:
        imm4, i_bit, imm3, imm8 = (value >> 12) & 0xF, (value >> 11) & 1, (value >> 8) & 7, value & 0xFF
        hw1 = 0xF240 | (i_bit << 10) | imm4
        n = 0
        for rd in range(16):
            enc = struct.pack("<HH", hw1, (imm3 << 12) | (rd << 8) | imm8)
            p = 0
            while True:
                j = data.find(enc, p)
                if j < 0:
                    break
                p = j + 1
                if j % 4 == 0:
                    n += 1
        print(f"  {name}: {n} MOVW site(s)")

    # And confirm the app really does import the entry point.
    for sym in (b"glGetIntegerv\0", b"glViewport\0"):
        print(f"  {sym[:-1].decode()} imported at {hex(data.find(sym)) if data.find(sym) >= 0 else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

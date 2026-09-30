# -*- coding: utf-8 -*-
"""Re-derive the exact clamp bounds in ZFFarmTileMap -setZoomOutAmount:.

Branch A (winSize.width <= 480 or no director): lower = 0.2, upper = 1.0
Branch B (winSize.width > 480):                 lower = 0.9 - width*0.01, upper = 2.0
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]


def f32(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<f", sl.data, off)[0]


def f64(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<d", sl.data, off)[0]


def pool(insn, imm):
    return ((insn + 4) & ~3) + imm


print("threshold s0 @0x7e1a :", f32(pool(0x7e1a, 0x2c4)))
print("multiplier s0 @0x7e58:", f32(pool(0x7e58, 0x288)))
print("const d17  @0x7e74   :", f64(pool(0x7e74, 0x260)))
print("branchA lower s20 @0x7e2c:", f32(pool(0x7e2c, 0x2b8)))
print()
print("d9 in branch A = 1.0  -> s18 (upper) = 1.0")
print("d9 in branch B = 2.0  -> s18 (upper) = 2.0")
print()
for w in (480, 960, 1024, 2048, 3072):
    lower = 0.9 - w * 0.01
    print(f"  width {w:5d}: branch {'A [0.2, 1.0]' if w <= 480 else f'B [{lower:.3f}, 2.0]'}")

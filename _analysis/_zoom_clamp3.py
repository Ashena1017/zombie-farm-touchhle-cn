# -*- coding: utf-8 -*-
"""Confirm the exact arithmetic of -setZoomOutAmount:'s clamp for our launch config.

Branch A (no map / winSize.width <= 480):  lower = 0.2,        upper = 1.0
Branch B (winSize.width > 480):            lower = 0.9 - w*0.01, upper = 2.0
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]
text = next(s for s in sl.sections if s.name == "__text")


def f32(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<f", sl.data, off)[0]


def f64(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<d", sl.data, off)[0]


def pool(insn, imm):
    return ((insn + 4) & ~3) + imm


print("branch-A lower (0x7e2c) :", f32(pool(0x7e2c, 0x2b8)))
print("branch-B base  (0x7e74) :", f64(pool(0x7e74, 0x260)), "(f64)")
print("branch-B coeff (0x7e58) :", f32(pool(0x7e58, 0x288)))
print("width threshold(0x7e1a) :", f32(pool(0x7e1a, 0x2c4)))
print()
print("d9 (upper bound register) is set to:")
print("   branch A (0x7e30): 1.0")
print("   branch B (0x7e78): 2.0")
print()
print("=> our launcher uses --device-family=ipad --scale-hack=1  ->  winSize.width = 1024")
print("   branch B: lower = 0.9 - 1024*0.01 = %.2f   (negative: never binds)" % (0.9 - 1024 * 0.01))
print("             upper = 2.0")
print("   so the game accepts (0, 2.0]; the wheel's own floor of 0.2 is the safety net.")
print()

# sanity: which branch is chosen, restated from the disassembly control flow
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
code = sl.data[text.offset + (0x7e1a - text.addr): text.offset + (0x7e88 - text.addr)]
print("control flow 0x7e1a..0x7e88:")
for ins in md.disasm(code, 0x7e1a):
    print(f"   0x{ins.address:06x}  {ins.mnemonic:<10} {ins.op_str}")

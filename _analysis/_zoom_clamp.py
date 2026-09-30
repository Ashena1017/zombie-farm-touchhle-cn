# -*- coding: utf-8 -*-
"""Resolve the float literals used by ZFFarmTileMap -setZoomOutAmount: to recover the clamp range."""
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
    if off is None:
        return None
    return struct.unpack_from("<f", sl.data, off)[0]

def f64(va):
    off = sl.addr_to_file(va)
    if off is None:
        return None
    return struct.unpack_from("<d", sl.data, off)[0]

# Thumb literal-pool address: (insn_addr + 4) & ~3, + imm
def pool(insn, imm):
    return ((insn + 4) & ~3) + imm

print("=== setZoomOutAmount: (imp 0x7dc1, thumb, so insn addr = imp-1) ===")
cands = [
    ("0x7e1a vldr s0,[pc,#0x2c4]  (compare threshold)", 0x7e1a, 0x2c4),
    ("0x7e2c vldr s20,[pc,#0x2b8] (low clamp candidate)", 0x7e2c, 0x2b8),
    ("0x7e58 vldr s0,[pc,#0x288]  (multiplier)", 0x7e58, 0x288),
    ("0x7e6a vldr d16,[pc,#0x264] (f64)", 0x7e6a, 0x264),
    ("0x7e74 vldr d17,[pc,#0x260] (f64)", 0x7e74, 0x260),
    ("0x7e96? s18 (high clamp) - find", None, None),
]
for label, insn, imm in cands:
    if insn is None:
        continue
    va = pool(insn, imm)
    print(f"  {label:52s} pool@0x{va:x}  f32={f32(va)}  f64={f64(va)}")

# s18 is loaded somewhere; scan whole method for vldr with d18/s18
print("\n  -- every vldr in the method with its pool value --")
md_start, md_end = 0x7dc0, 0x80ec
text = next(s for s in sl.sections if s.name == "__text")
code = sl.data[text.offset + (md_start - text.addr): text.offset + (md_end - text.addr)]
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
for ins in md.disasm(code, md_start):
    if ins.mnemonic in ("vldr", "vldm") and "pc" in ins.op_str:
        try:
            imm = ins.operands[1].mem.disp
        except Exception:
            continue
        va = pool(ins.address, imm)
        tgt = ins.op_str.split(",")[0].strip()
        print(f"    0x{ins.address:06x} {ins.mnemonic} {tgt:6s} imm=0x{imm:x} -> pool@0x{va:x} f32={f32(va)} f64={f64(va)}")

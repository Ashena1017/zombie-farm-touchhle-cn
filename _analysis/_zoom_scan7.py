# -*- coding: utf-8 -*-
"""Fast targeted scan for code referencing the zoom selectors' selref slots."""
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

selrefs = next(s for s in sl.sections if s.name == "__objc_selrefs")
methname = next(s for s in sl.sections if s.name == "__objc_methname")
text = next(s for s in sl.sections if s.name == "__text")
print(f"__text addr=0x{text.addr:x} size=0x{text.size:x}")
print(f"__objc_selrefs addr=0x{selrefs.addr:x} size=0x{selrefs.size:x}")

# selref slot VA for each target selector
targets = {}
for slot in range(selrefs.addr, selrefs.addr + selrefs.size, 4):
    off = selrefs.offset + (slot - selrefs.addr)
    va = struct.unpack_from("<I", sl.data, off)[0]
    if methname.addr <= va < methname.addr + methname.size:
        name = sl.cstr(va)
        if name in ("setZoomOutAmount:", "resetCameraWithZoom:", "resetCamera",
                    "scaleCompensation:", "zoomFactor"):
            targets[slot] = name
print("\nselref slots:", {hex(k): v for k, v in targets.items()})

# method index for owner attribution
idx = {}
for m in sl.methods:
    if m.file_offset is not None:
        idx[m.imp & ~1] = (m.cls, m.selector)

def owner_at(addr):
    prev = max((x for x in idx if x <= addr), default=None)
    if prev is None or addr - prev > 0x4000:
        return ""
    c, s = idx[prev]
    return f"{c} {s} +{addr - prev:#x}"

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

code = sl.data[text.offset:text.offset + text.size]
insns = list(md.disasm(code, text.addr))
print(f"disassembled {len(insns)} thumb insns")

# 1) direct literal-pool references inside __text
print("\n=== literal 32-bit values equal to a target selref slot (inside __text) ===")
for slot, name in targets.items():
    needle = struct.pack("<I", slot)
    start = 0
    while True:
        p = code.find(needle, start)
        if p < 0:
            break
        start = p + 1
        if p % 4 == 0:
            va = text.addr + p
            print(f"   literal 0x{slot:x} ({name}) at 0x{va:x}  owner=[{owner_at(va)}]")

# 2) movw/movt pairs building the slot address
print("\n=== movw/movt pairs building a target selref slot ===")
for i, ins in enumerate(insns):
    if ins.mnemonic != "movw":
        continue
    try:
        rd = ins.operands[0].reg
        imm = ins.operands[1].imm
    except Exception:
        continue
    if i + 1 < len(insns) and insns[i + 1].mnemonic == "movt":
        nxt = insns[i + 1]
        if nxt.operands[0].reg == rd:
            val = (nxt.operands[1].imm << 16) | (imm & 0xFFFF)
            if val in targets:
                print(f"   0x{ins.address:x} movw/movt -> 0x{val:x} ({targets[val]})  owner=[{owner_at(ins.address)}]")

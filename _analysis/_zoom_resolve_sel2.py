# -*- coding: utf-8 -*-
"""Resolve the exact selectors used by -setZoomOutAmount:'s runAction: path.

The pc-relative `add rX, pc` uses base = insn_addr + 4 (Thumb), so the slot is
(insn_addr_of_add + 4) + imm. We scan a small window to be robust.
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
methname = next(s for s in sl.sections if s.name == "__objc_methname")
selrefs = next(s for s in sl.sections if s.name == "__objc_selrefs")


def rd32(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<I", sl.data, off)[0]


def cstr(va):
    off = sl.addr_to_file(va)
    if off is None:
        return f"<0x{va:x} not file-backed>"
    end = sl.data.index(b"\0", off)
    return sl.data[off:end].decode("ascii", "replace")


def in_methname(va):
    return va is not None and methname.addr <= va < methname.addr + methname.size


def in_selrefs(va):
    return va is not None and selrefs.addr <= va < selrefs.addr + selrefs.size


# The `add rX, pc` instructions of interest (from the annotated dump):
#   0x7ee6  add r1, pc     (r1 was movw/movt = 0x38bc26)
#   0x7f08  add r0, pc     (r0 was movw/movt = 0x38bc08)
for add_addr, imm32, label in ((0x7EE6, 0x38BC26, "action factory selref"),
                               (0x7F08, 0x38BC08, "runAction: selref")):
    print(f"\n=== {label} (add rX,pc @0x{add_addr:x}, base const 0x{imm32:x}) ===")
    for delta in (2, 4, 6):
        slot = (add_addr + delta) + imm32
        v = rd32(slot)
        tag = ""
        if in_methname(v):
            tag = f' -> SEL "{cstr(v)}"'
        elif in_selrefs(v):
            tag = f" -> selref slot (value 0x{v:x})"
        print(f"   pc+{delta}: slot=0x{slot:x}  [slot]=0x{v:x}{tag}")

# Direct approach: scan every selref slot and print ones whose string we want.
print("\n=== all selrefs whose name mentions Scale/Action/zoom ===")
for slot in range(selrefs.addr, selrefs.addr + selrefs.size, 4):
    v = rd32(slot)
    if in_methname(v):
        name = cstr(v)
        if any(k in name for k in ("ScaleTo", "runAction", "numberOfRunningActions", "Zoom")):
            print(f"   slot=0x{slot:x} -> \"{name}\"")

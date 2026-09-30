# -*- coding: utf-8 -*-
"""Dump the FULL ZFFarmTileMap -ccTouchMoved:withEvent: with resolved selrefs, to a file."""
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

def pool_va(insn_addr, imm):
    return ((insn_addr + 4) & ~3) + imm

def slot_sel(insn_addr, imm):
    va = pool_va(insn_addr, imm)
    off = sl.addr_to_file(va)
    if off is None:
        return None, va
    selva = struct.unpack_from("<I", sl.data, off)[0]
    if methname.addr <= selva < methname.addr + methname.size:
        return sl.cstr(selva), va
    return None, va

def f32at(va):
    off = sl.addr_to_file(va)
    if off is None:
        return None
    return struct.unpack_from("<f", sl.data, off)[0]

ranges = {}
for m, s, e in sl.method_ranges():
    ranges[(m.cls, m.selector)] = (m, s, e)

OUT = ROOT / "_analysis" / "_zoom_ccTouchMoved.txt"
lines = []

for cls, sel in [("ZFFarmTileMap", "ccTouchMoved:withEvent:"),
                 ("ZFFarmTileMap", "ccTouchBegan:withEvent:"),
                 ("ZFFarmTileMap", "registerWithTouchDispatcher"),
                 ("ZFFarmTileMap", "resetTouchState"),
                 ("ZFFarmTileMap", "dragFrom:to:")]:
    m, start, end = ranges[(cls, sel)]
    lines.append(f"\n{'='*100}\n{cls} -{sel}   imp=0x{m.imp:x}  range=[0x{start:x}, {hex(end) if end else '?'})\n{'='*100}")
    size = (end - start) if end else 0x400
    code = sl.data[text.offset + (start - text.addr): text.offset + (start - text.addr) + size]
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    for ins in md.disasm(code, start):
        note = ""
        ops = ins.op_str
        if ins.mnemonic in ("ldr", "vldr") and "pc" in ops:
            try:
                imm = ins.operands[1].mem.disp
            except Exception:
                imm = None
            if imm is not None:
                va = pool_va(ins.address, imm)
                s, _ = slot_sel(ins.address, imm)
                if s:
                    note = f"   ; SEL \"{s}\""
                else:
                    fv = f32at(va)
                    if fv is not None and fv == fv and abs(fv) < 1e7:
                        note = f"   ; pool 0x{va:x} f32={fv}"
                    else:
                        note = f"   ; pool 0x{va:x}"
        lines.append(f"  0x{ins.address:06x}  {ins.mnemonic:<10} {ops}{note}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} ({len(lines)} lines)")

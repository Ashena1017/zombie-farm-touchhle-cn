# -*- coding: utf-8 -*-
"""Focused disassembly of ZFFarmTileMap -ccTouchMoved:withEvent: around the setZoomOutAmount: call,
with pc-relative selref + literal-pool resolution."""
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
objc_data = next(s for s in sl.sections if s.name == "__objc_data")

def rd32(va):
    off = sl.addr_to_file(va)
    if off is None:
        return None
    return struct.unpack_from("<I", sl.data, off)[0]

def f32(va):
    off = sl.addr_to_file(va)
    if off is None:
        return None
    return struct.unpack_from("<f", sl.data, off)[0]

def pool(insn, imm):
    return ((insn + 4) & ~3) + imm

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

# annotate registers for the pc-relative add/ldr pairs
START, END = 0x6100, 0x63dc
code = sl.data[text.offset + (START - text.addr): text.offset + (END - text.addr)]

# First pass: emulate the simple "movw/movt/add pc/ldr" pattern to resolve selrefs,
# and "movw/movt/add pc/ldr" for ivar offsets.
reg = {}   # reg -> ('sel', name) | ('ivar', off) | ('pool', va) | ('const', v)
print("=== ZFFarmTileMap -ccTouchMoved:withEvent: (annotated) ===\n")
for ins in md.disasm(code, START):
    m, ops = ins.mnemonic, ins.op_str
    note = ""
    try:
        if m in ("movw", "mov") and len(ins.operands) == 2 and ins.operands[0].type == 1:
            reg[ins.reg_name(ins.operands[0].reg)] = ("const", ins.operands[1].imm)
        elif m == "movt" and len(ins.operands) == 2 and ins.operands[0].type == 1:
            r = ins.reg_name(ins.operands[0].reg)
            base = reg.get(r, ("const", 0))[1]
            reg[r] = ("const", (ins.operands[1].imm << 16) | (base & 0xFFFF))
        elif m == "add" and len(ins.operands) == 2 and ins.reg_name(ins.operands[1].reg) == "pc":
            r = ins.reg_name(ins.operands[0].reg)
            base = reg.get(r, ("const", 0))[1]
            reg[r] = ("addr", ((ins.address + 4) & ~3) + base)
        elif m == "ldr" and len(ins.operands) == 2 and ins.operands[1].type == 3:
            r = ins.reg_name(ins.operands[0].reg)
            mem = ins.operands[1].mem
            breg = ins.reg_name(mem.base)
            if breg == "pc":
                va = pool(ins.address, mem.disp)
                val = rd32(va)
                if val is not None and methname.addr <= val < methname.addr + methname.size:
                    reg[r] = ("sel", sl.cstr(val))
                    note = f'   ; SEL "{sl.cstr(val)}"'
                else:
                    reg[r] = ("poolval", val)
                    note = f"   ; pool 0x{va:x} = 0x{val:x} f32={f32(va)}"
            elif reg.get(breg, ("", 0))[0] == "addr":
                va = reg[breg][1] + mem.disp
                val = rd32(va)
                if val is not None and methname.addr <= val < methname.addr + methname.size:
                    reg[r] = ("sel", sl.cstr(val))
                    note = f'   ; SEL "{sl.cstr(val)}"'
                else:
                    note = f"   ; [0x{va:x}] = 0x{val if val is None else hex(val)}"
            else:
                note = ""
        elif m == "vldr" and "pc" in ops:
            try:
                imm = ins.operands[1].mem.disp
            except Exception:
                imm = None
            if imm is not None:
                va = pool(ins.address, imm)
                note = f"   ; pool 0x{va:x} f32={f32(va)} f64={struct.unpack_from('<d', sl.data, sl.addr_to_file(va))[0] if sl.addr_to_file(va) else None}"
        elif m == "blx":
            pass
    except Exception as e:
        note = f"   <annot err {e}>"

    extra = ""
    if m == "blx" and "#0x2d014c" in ops:
        # objc_msgSend: r1 holds sel
        s = reg.get("r1")
        if s and s[0] == "sel":
            extra = f'   ; objc_msgSend sel="{s[1]}"'
    if m == "blx" and "#0x2d0170" in ops:
        s = reg.get("r2")
        if s and s[0] == "sel":
            extra = f'   ; objc_msgSend_stret sel="{s[1]}"'
    print(f"  0x{ins.address:06x}  {m:<10} {ops}{note}{extra}")

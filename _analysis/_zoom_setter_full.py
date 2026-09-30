# -*- coding: utf-8 -*-
"""Full annotated disassembly of ZFFarmTileMap -setZoomOutAmount: (0x7dc0..0x80ec)."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, read_ivars  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]
selrefs = next(s for s in sl.sections if s.name == "__objc_selrefs")
methname = next(s for s in sl.sections if s.name == "__objc_methname")
text = next(s for s in sl.sections if s.name == "__text")

cls = classes_by_name(sl)
_c, info = cls["ZFFarmTileMap"]
by_off = {iv["offset"]: iv["name"] for iv in read_ivars(sl, info["ivars"])}

def rd32(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<I", sl.data, off)[0]

def f32(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<f", sl.data, off)[0]

def f64(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<d", sl.data, off)[0]

START, END = 0x7dc0, 0x80ec
code = sl.data[text.offset + (START - text.addr): text.offset + (END - text.addr)]
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
reg = {}
for ins in md.disasm(code, START):
    m, ops = ins.mnemonic, ins.op_str
    note = ""
    try:
        if m in ("movw", "mov") and len(ins.operands) == 2 and ins.operands[0].type == 1:
            reg[ins.reg_name(ins.operands[0].reg)] = ("const", ins.operands[1].imm)
        elif m == "movt" and len(ins.operands) == 2 and ins.operands[0].type == 1:
            r = ins.reg_name(ins.operands[0].reg)
            reg[r] = ("const", (ins.operands[1].imm << 16) | (reg.get(r, ("const", 0))[1] & 0xFFFF))
        elif m == "add" and len(ins.operands) == 2 and ins.reg_name(ins.operands[1].reg) == "pc":
            r = ins.reg_name(ins.operands[0].reg)
            reg[r] = ("addr", ((ins.address + 4) & ~3) + reg.get(r, ("const", 0))[1])
        elif m == "ldr" and len(ins.operands) == 2 and ins.operands[1].type == 3:
            r = ins.reg_name(ins.operands[0].reg)
            mem = ins.operands[1].mem
            breg = ins.reg_name(mem.base)
            if breg == "pc":
                va = ((ins.address + 4) & ~3) + mem.disp
                val = rd32(va)
                if val is not None and methname.addr <= val < methname.addr + methname.size:
                    reg[r] = ("sel", sl.cstr(val)); note = f'   ; SEL "{sl.cstr(val)}"'
                elif val is not None and 0 < val < 0x1000:
                    reg[r] = ("ivoff", val)
                    note = f"   ; ivar +0x{val:x} = {by_off.get(val, '?')}"
                else:
                    reg[r] = ("pool", val); note = f"   ; [0x{va:x}]=0x{val if val is None else hex(val)}"
            elif reg.get(breg, ("", 0))[0] == "addr":
                va = reg[breg][1] + mem.disp
                val = rd32(va)
                if val is not None and methname.addr <= val < methname.addr + methname.size:
                    reg[r] = ("sel", sl.cstr(val)); note = f'   ; SEL "{sl.cstr(val)}"'
                else:
                    note = f"   ; [0x{va:x}]=0x{val if val is None else hex(val)}"
        elif m == "vldr" and "pc" in ops:
            imm = ins.operands[1].mem.disp
            va = ((ins.address + 4) & ~3) + imm
            note = f"   ; pool 0x{va:x} f32={f32(va)} f64={f64(va)}"
    except Exception as e:
        note = f"   <err {e}>"
    extra = ""
    if m == "blx":
        if "#0x2d014c" in ops:
            s = reg.get("r1")
            if s and s[0] == "sel": extra = f'   ; msgSend "{s[1]}"'
        elif "#0x2d0170" in ops:
            s = reg.get("r2")
            if s and s[0] == "sel": extra = f'   ; msgSend_stret "{s[1]}"'
    print(f"  0x{ins.address:06x}  {m:<10} {ops}{note}{extra}")

"""#4 follow-up: user sees (9) sitting left of (10). Question: is toolName's
position set by MORE THAN ONE function (i.e. per-count repositioning)?

Scan every ZFToolsLayer method (sub9, the live slice) for
setPosition:/setAnchorPoint: msgsends with correct capstone reg constants,
print method + context for each hit.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC,
                                ARM_REG_R0, ARM_REG_R1)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v20fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
txt = next(s for s in sl.sections if s.name == "__text")


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a, limit=100):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + limit)
    except ValueError:
        return None
    try:
        s = sl.data[o:e].decode("utf-8")
    except Exception:
        return None
    return s if s and s.isprintable() else None


sel_of = {}
for sec in sl.sections:
    if sec.name != "__objc_selrefs":
        continue
    for off in range(0, sec.size, 4):
        a = sec.addr + off
        v = u32(a)
        if v:
            t = cs_(v)
            if t and not t.startswith("<addr"):
                sel_of[a] = t
name_of_cstr = {}
for a, t in sel_of.items():
    name_of_cstr.setdefault(u32(a), t)

WANT = {"setPosition:", "setAnchorPoint:"}

cb = classes_by_name(sl)
c, info = cb["ZFToolsLayer"]
methods = sorted([(m.imp & ~1, m.selector) for m in all_methods(sl, c, info) if m.imp])

MSGSEND = 0x2D014C
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

for idx, (imp, sel) in enumerate(methods):
    end = methods[idx + 1][0] if idx + 1 < len(methods) else imp + 0x2000
    o = sl.addr_to_file(imp)
    if o is None:
        continue
    ins = list(md.disasm(sl.data[o:o + (end - imp)], imp))
    regs = {}
    for i, x in enumerate(ins):
        if not x.id or not x.operands:
            regs = {}
            continue
        ops = x.operands
        m = x.mnemonic.split(".")[0]
        if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            imm = ops[-1].imm & 0xFFFF
            regs[dst] = imm if m == "movw" else ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF))
        elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
            regs[ops[0].reg] = regs.get(ops[1].reg)
        elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ops[-1].imm
        elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
                and ops[1].reg == ARM_REG_PC:
            v = regs.get(ops[0].reg)
            if v is not None:
                regs[ops[0].reg] = ((x.address + 4) + v) & 0xFFFFFFFF
        elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            if mm.base == ARM_REG_PC:
                pcw = (x.address + 4) & ~3
                ix = regs.get(mm.index) if mm.index else 0
                regs[ops[0].reg] = u32((pcw + (mm.disp or 0) + ix) & 0xFFFFFFFF) if ix is not None else None
            elif mm.base in regs and regs[mm.base] is not None and not mm.index:
                regs[ops[0].reg] = u32((regs[mm.base] + (mm.disp or 0)) & 0xFFFFFFFF)
            else:
                regs[ops[0].reg] = None
        elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
            t = ops[0].imm & ~1
            if t == MSGSEND:
                r1 = regs.get(ARM_REG_R1)
                nm = name_of_cstr.get(r1, sel_of.get(r1)) if r1 is not None else None
                if nm in WANT:
                    print("### %s @ %#x: %s r0=%s" % (
                        sel, x.address, nm,
                        hex(regs[ARM_REG_R0]) if regs.get(ARM_REG_R0) is not None else "?"))
            for r in (ARM_REG_R0, ARM_REG_R1, 2, 3, 12):
                regs.pop(r, None)

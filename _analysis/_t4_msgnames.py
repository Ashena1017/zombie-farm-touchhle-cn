"""#4 follow-up v2: name EVERY msgsend inside ZFToolManager -toolSelected:
(sub9 0x20D3C..0x21330) with the fixed reg constants. Looking for any
setPosition:/setAnchorPoint:/contentSize/boundingBox-class call that would
reposition the toolName label per count (the user sees (9) left of (10)).
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC,
                                ARM_REG_R0, ARM_REG_R1)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v20fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a, limit=120):
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

# CFString objects -> string (layout [isa,flags,data,len])
cf_of = {}
for sec in sl.sections:
    if sec.name != "__cfstring":
        continue
    for off in range(0, sec.size, 16):
        a = sec.addr + off
        data = u32(a + 8)
        ln = u32(a + 12)
        if data is not None and ln is not None and ln <= 64:
            s = cs_(data, 70)
            if s is not None:
                cf_of[a] = s


def nm(v):
    if v is None:
        return "?"
    if v in name_of_cstr:
        return name_of_cstr[v]
    if v in sel_of:
        return sel_of[v] + " [entry]"
    if v in cf_of:
        return "CFSTR %r" % cf_of[v]
    s = cs_(v, 40)
    if s:
        return "CSTR %r" % s
    return hex(v)


LO, HI = 0x20D3C, 0x21330
MSGSEND, STRUCTRET = 0x2D014C, 0x2D0170
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
o = sl.addr_to_file(LO)
ins = list(md.disasm(sl.data[o:o + (HI - LO)], LO))
regs = {}
for x in ins:
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
        if t in (MSGSEND, STRUCTRET):
            print("%#x %-4s r1=%-42s r0=%-24s r2=%s r3=%s" % (
                x.address, "msg" if t == MSGSEND else "sr",
                nm(regs.get(ARM_REG_R1)), nm(regs.get(ARM_REG_R0)),
                nm(regs.get(2)), nm(regs.get(3))))
        for r in (ARM_REG_R0, ARM_REG_R1, 2, 3, 12):
            regs.pop(r, None)

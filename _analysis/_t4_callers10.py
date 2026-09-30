"""#4 v10: find setToolLabel: callers (sub9) accepting BOTH selector models:
  (a) r1 == selref ENTRY address (entry points at selector cstring), or
  (b) r1 == selector CSTRING address directly (== u32(entry)).
Also fix ldr-literal tracking to keep the ENTRY address when the loaded value
is needed later (two-stage: entry -> content).
Track: reg -> ('entry', addr) | ('imm', value) | ('mem', value|None).
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

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
txt = next(s for s in sl.sections if s.name == "__text")


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a, limit=160):
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

SET_ENTRY = next(a for a, t in sel_of.items() if t == "setToolLabel:")
SET_CSTR = u32(SET_ENTRY)
print("setToolLabel: entry=%#x cstring=%#x" % (SET_ENTRY, SET_CSTR))

MSGSEND = 0x2D014C
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
ins = list(md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr))

regs = {}
hist = []
hits = []
for x in ins:
    line = "%#010x  %-8s %s" % (x.address, x.mnemonic, x.op_str)
    if not x.id or not x.operands:
        regs = {}
        hist.append(line)
        if len(hist) > 70:
            hist.pop(0)
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
            idx = regs.get(mm.index) if mm.index else 0
            if idx is not None:
                eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                regs[ops[0].reg] = u32(eff)
            else:
                regs[ops[0].reg] = None
        elif mm.base in regs and regs[mm.base] is not None and not mm.index:
            # ldr rD, [rB] or [rB, #off]: deref tracked pointer
            regs[ops[0].reg] = u32((regs[mm.base] + (mm.disp or 0)) & 0xFFFFFFFF)
        else:
            regs[ops[0].reg] = None
    elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm & ~1
        if t == MSGSEND and regs.get(ARM_REG_R1) in (SET_ENTRY, SET_CSTR):
            hits.append((x.address, list(hist)))
        for r in (ARM_REG_R0, ARM_REG_R1, 2, 3, 12):
            regs.pop(r, None)
    hist.append(line)
    if len(hist) > 70:
        hist.pop(0)

print("hits: %d" % len(hits))
for addr, ctx in hits:
    print("\n##### setToolLabel: call @ %#x #####" % addr)
    for ln in ctx[-40:]:
        print("   " + ln)
    print("   %#010x  blx      objc_msgSend   <<<<" % addr)

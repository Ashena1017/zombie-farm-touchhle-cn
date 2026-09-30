#!/usr/bin/env python3
"""Byte-exact decode of the `Fertilized by %@!` float site (sub9 0x2a0a0..0x2a0f0),
resolving every PIC delta idiom by hand (no annotator heuristics).
"""
from __future__ import annotations

import pathlib as _pl
import struct
import sys
import zipfile

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
LO, HI = 0x2A0A0, 0x2A0F0

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)


def rd(a, n):
    o = sl.addr_to_file(a)
    return sl.data[o:o + n] if o is not None else None


def u32(a):
    b = rd(a, 4)
    return struct.unpack("<I", b)[0] if b else None


def cstr(a, n=140):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + n)
    except ValueError:
        return None
    try:
        return sl.data[o:e].decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


def sec(a):
    for s in sl.sections:
        if s.addr <= a < s.addr + s.size:
            return s.name
    return None


def describe(a):
    if a is None:
        return ""
    s = sec(a)
    if s == "__objc_selrefs":
        return "SEL %r" % cstr(u32(a))
    if s in ("__cfstring", "__objc_cfstring"):
        p, ln = u32(a + 8), u32(a + 12)
        return "CFSTR %r" % cstr(p, (ln or 60) + 1)
    if s in ("__cstring", "__objc_methname"):
        return "CSTR %r" % cstr(a)
    if s == "__objc_classrefs":
        return "classref slot -> %s" % hex(u32(a) or 0)
    return s or "?"


print("raw bytes %#x..%#x:" % (LO, HI))
print("   " + rd(LO, HI - LO).hex())

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
regs = {}
for x in md.disasm(rd(LO, HI - LO), LO):
    ops = x.operands
    note = ""
    m = x.mnemonic.split(".")[0]
    pc = x.address + 4
    pcw = (x.address + 4) & ~3
    dst = nv = None
    if m == "add" and len(ops) >= 2 and ops[0].type == 1 and ops[1].type == 1 and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if isinstance(v, int):
            nv = (pc + v) & 0xFFFFFFFF
            dst = ops[0].reg
            note = "=> %#x  %s" % (nv, describe(nv))
    elif m == "ldr" and len(ops) == 2 and ops[0].type == 1 and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        dst = ops[0].reg
        if mm.base == ARM_REG_PC:
            idx = regs.get(mm.index) if mm.index else 0
            if isinstance(idx, int):
                eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                nv = u32(eff)
                note = "ld from %#x = %s | %s" % (eff, hex(nv) if nv is not None else "?", describe(eff))
        else:
            nv = None
    elif m in ("movw", "movt") and ops[0].type == 1 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) if m == "movt" else imm
        note = "imm %#x" % nv
    elif m in ("mov", "movs") and len(ops) >= 2 and ops[0].type == 1 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
        note = "imm %#x" % nv
    elif m == "mov" and len(ops) == 2 and ops[0].type == 1 and ops[1].type == 1:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
    elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm
        note = "call %#x  (%s)" % (t, sec(t) or "?")
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)
        dst = None
    else:
        dst = None
    print("  %#010x  %-8s %-30s %-34s %s"
          % (x.address, x.mnemonic, x.op_str,
             " ".join("r%d=%s" % (r, hex(v) if isinstance(v, int) else "?")
                      for r, v in sorted(regs.items()) if r in (0, 1, 2, 3, 5, 10)), note))
    if dst is not None:
        regs[dst] = nv

#!/usr/bin/env python3
"""Resolve every `add rX, pc` / literal-load materialisation in a sub9 range to its
target object (SEL / CFString / CSTR / class), by simulating the delta idiom
linearly from the start of the range.

Usage: python _analysis/_zfz_mat.py LO HI
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
from inspect_v3_facts import class_ro, classes_by_name  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
LO, HI = int(sys.argv[1], 0), int(sys.argv[2], 0)

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
by = classes_by_name(sl)
rev = {c: n for n, (c, i) in by.items()}


def sec(a):
    for s in sl.sections:
        if s.addr <= a < s.addr + s.size:
            return s.name
    return None


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cstr(a, n=120):
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


def describe(a):
    if a is None:
        return ""
    s = sec(a)
    if s in ("__objc_selrefs",):
        return "SEL %r" % cstr(u32(a))
    if s in ("__cfstring", "__objc_cfstring"):
        p, ln = u32(a + 8), u32(a + 12)
        return "CFSTR %r" % cstr(p, (ln or 60) + 1)
    if s == "__objc_classrefs":
        v = u32(a)
        return "classref @%s" % (rev.get(v) or hex(v or 0))
    if s in ("__cstring", "__objc_methname"):
        return "CSTR %r" % cstr(a)
    if s == "__text":
        return ""
    return s or ""


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
o = sl.addr_to_file(LO)
regs = {}
for x in md.disasm(sl.data[o:o + (HI - LO)], LO):
    if not x.id or not x.operands:
        regs = {}
        print("  %#010x  %-8s %-40s" % (x.address, x.mnemonic, x.op_str))
        continue
    ops = x.operands
    m = x.mnemonic.split(".")[0]
    pc = x.address + 4
    pcw = (x.address + 4) & ~3
    dst = nv = None
    note = ""
    if m == "add" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and \
            ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if isinstance(v, int):
            nv = (pc + v) & 0xFFFFFFFF
            dst = ops[0].reg
            note = describe(nv)
    elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        dst = ops[0].reg
        if mm.base == ARM_REG_PC:
            idx = regs.get(mm.index) if mm.index else 0
            if isinstance(idx, int):
                eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                nv = u32(eff)
                note = describe(eff) or ("@%#x=%s" % (eff, hex(nv) if nv else "0"))
        else:
            nv = None
    elif m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) if m == "movt" else imm
    elif m in ("mov", "movs") and len(ops) >= 2 and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
    elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
    elif m in ("bl", "blx", "b"):
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)
        dst = None
    else:
        dst = None
    if dst is not None:
        regs[dst] = nv
    print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, note))

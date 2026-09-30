#!/usr/bin/env python3
"""Accurate value tracker for 32-bit ARM/Thumb, to find who uses a given address.

Why this exists: neither of the naive approaches works on this binary.

  * Searching for the target as a raw 4-byte pattern misses almost everything,
    because addresses are materialised at runtime, not stored literally.
  * Treating every literal-pool word as a pointer is *wrong*: these slices use
    `ldr rS, [pc, #imm]` to load a **delta**, then `add rD, pc, rS` at a
    different instruction to materialise the address. The base register is the
    `add` site's PC, not the load site's PC. Conflating the two produces
    plausible-looking but false references.

So this tracks register values linearly with skipdata enabled, modelling:

    mov / movs / movw / movt      immediate
    ldr  rX, [pc, #imm]           literal word
    ldr  rX, [pc, rY]             literal word at (pc + rY)
    add  rX, pc, rY               pc + rY          <- the idiom above
    add  rX, rY, #imm / add rX,rY,rZ
    ldr  rX, [rY] / [rY, #imm]    dereference, when rY is known

and reports every instruction where a register becomes equal to the target.

Usage: value_xref.py TARGET [--ipa NAME] [--sub 6] [--all]
"""
from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
DEFAULT_IPA = f"{BASE}.fixed-fonts-v5.ipa"


def sec_name(sl, a):
    for x in sl.sections:
        if x.addr <= a < x.addr + x.size:
            return x.name
    return None


def cstr(sl, a, n=100):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    b = sl.data[o:o + n]
    i = b.find(b"\0")
    return b[:i if i >= 0 else n].decode("utf-8", "replace")


def u32(sl, a):
    o = sl.addr_to_file(a)
    return None if o is None else struct.unpack_from("<I", sl.data, o)[0]


def owner(sl, addr):
    best = None
    for m in sl.methods:
        if m.file_offset is None:
            continue
        s = m.imp & ~1
        if s <= addr and (best is None or s > best[0]):
            best = (s, m)
    if not best:
        return "?"
    return (f"{best[1].cls}[{best[1].kind}] {best[1].selector}"
            f"+{addr - best[0]:#x}")


def describe(sl, a):
    s = sec_name(sl, a)
    if s == "__objc_selrefs":
        return f"selref -> SEL:{cstr(sl, u32(sl, a))!r}"
    if s == "__cfstring":
        p, ln = u32(sl, a + 8), u32(sl, a + 12)
        return f"CFSTR({cstr(sl, p, min((ln or 60) + 1, 100))!r})"
    if s == "__objc_classrefs":
        return f"classref -> @{u32(sl, a):#x}"
    if s == "__objc_methname":
        return f"methname {cstr(sl, a)!r}"
    if s:
        return s
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=lambda x: int(x, 0))
    ap.add_argument("--ipa", default=DEFAULT_IPA)
    ap.add_argument("--sub", type=int, default=None)
    ap.add_argument("--max", type=int, default=40)
    args = ap.parse_args()

    with zipfile.ZipFile(ROOT / args.ipa) as z:
        fat = z.read(EXECUTABLE)

    print(f"target {args.target:#x} = {describe(parse_fat(fat)[0], args.target)}")

    for sl in parse_fat(fat):
        if args.sub is not None and sl.subtype != args.sub:
            continue
        thumb = sl.subtype == 9
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        md.skipdata = True

        hits = []
        for sec in sl.sections:
            if sec.name != "__text":
                continue
            regs: dict[int, int | None] = {}
            for ins in md.disasm(sl.data[sec.offset:sec.offset + sec.size],
                                 sec.addr):
                if ins.id == 0 or not ins.operands:
                    continue
                ops = ins.operands
                m = ins.mnemonic.split(".")[0]
                pc = (ins.address + 4) & ~3 if thumb else ins.address + 8

                def val(op):
                    if op.type == ARM_OP_IMM:
                        return op.imm & 0xFFFFFFFF
                    if op.type == ARM_OP_REG:
                        return regs.get(op.reg)
                    return None

                newval = None
                dst = None
                if m in ("mov", "movs", "movw", "movt") and len(ops) == 2 \
                        and ops[0].type == ARM_OP_REG:
                    dst = ops[0].reg
                    if ops[1].type == ARM_OP_IMM:
                        if m == "movt":
                            newval = ((regs.get(dst) or 0) & 0xFFFF) | \
                                     ((ops[1].imm & 0xFFFF) << 16)
                        else:
                            newval = ops[1].imm & 0xFFFFFFFF
                    elif ops[1].type == ARM_OP_REG:
                        newval = regs.get(ops[1].reg)
                elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG:
                    dst = ops[0].reg
                    mem = ops[1]
                    if mem.type == ARM_OP_MEM and mem.mem.base == ARM_REG_PC:
                        iv = regs.get(mem.mem.index) if mem.mem.index else 0
                        if iv is not None:
                            addr = (pc & ~3 if thumb else pc) + mem.mem.disp + iv
                            # A selref/ivar is referenced by *addressing* it, not by
                            # loading its value: `ldr rX,[pc,rY]` puts the slot's
                            # contents in rX, so comparing rX against the slot
                            # address never matches. Record the effective address too.
                            if addr == args.target:
                                hits.append((ins, dict(regs)))
                            newval = u32(sl, addr)
                        else:
                            newval = None
                    elif mem.type == ARM_OP_MEM and mem.mem.base != ARM_REG_PC:
                        b = regs.get(mem.mem.base)
                        if b is not None and not mem.mem.index:
                            newval = u32(sl, (b + mem.mem.disp) & 0xFFFFFFFF)
                        else:
                            newval = None
                elif m == "add" and ops[0].type == ARM_OP_REG:
                    dst = ops[0].reg
                    if len(ops) == 3:
                        a, b = val(ops[1]), val(ops[2])
                        if ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
                            a = pc
                        if ops[2].type == ARM_OP_REG and ops[2].reg == ARM_REG_PC:
                            b = pc
                        newval = None if a is None or b is None else (a + b) & 0xFFFFFFFF
                    elif len(ops) == 2:
                        # `add rX, pc` - the operand IS pc, so val() would look up
                        # an unset register and lose the value. Handle it directly.
                        if ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
                            newval = pc
                        else:
                            b = val(ops[1])
                            newval = None if b is None else (b + pc) & 0xFFFFFFFF
                elif m == "sub" and len(ops) == 3 and ops[0].type == ARM_OP_REG:
                    dst = ops[0].reg
                    a, b = val(ops[1]), val(ops[2])
                    newval = None if a is None or b is None else (a - b) & 0xFFFFFFFF
                elif m in ("orr", "add") and len(ops) == 3 and ops[0].type == ARM_OP_REG:
                    dst = ops[0].reg
                    a, b = val(ops[1]), val(ops[2])
                    newval = None if a is None or b is None else (a | b) & 0xFFFFFFFF

                if dst is not None:
                    regs[dst] = newval
                    if newval == args.target:
                        hits.append((ins, dict(regs)))

        print(f"\n===== sub{sl.subtype}: {len(hits)} site(s) where a register "
              f"== {args.target:#x} =====")
        for ins, _ in hits[:args.max]:
            print(f"  {ins.address:#08x} {ins.mnemonic:<8} {ins.op_str:<30} "
                  f"{owner(sl, ins.address)}")
        if len(hits) > args.max:
            print(f"  ... and {len(hits) - args.max} more")


if __name__ == "__main__":
    raise SystemExit(main())

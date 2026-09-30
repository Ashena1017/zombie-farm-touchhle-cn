#!/usr/bin/env python3
"""Dataflow check for the `Fertilized by %@!` float site (sub9 0x2a0dc):

  - what is the LAST write to [sp] that reaches 0x2a0dc  (the `table:` argument)
  - what are r2 / r3 at that point                        (key: / value:)
  - who references the CFString 'Arial-BoldMT' @0x3a3570

Usage: python _analysis/_zfz_table_arg2.py
"""
from __future__ import annotations

import bisect
import pathlib as _pl
import struct
import sys
from collections import deque

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC, ARM_REG_SP  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range("ZFToolManager", "popGameActionAndExecute:deltaTime:")
rows = a.annotate(a.disasm(start, end))
ins = [x for x, _, _ in rows]
by = {x.address: i for i, x in enumerate(ins)}

TARGET = 0x2A0DC


def is_branch(x):
    return x.mnemonic.startswith("b") and x.mnemonic not in ("bic", "bfi", "bfc")


def terminates(x):
    return (x.mnemonic in ("b", "b.w") or x.mnemonic.startswith("bx")
            or (x.mnemonic.startswith("pop") and "pc" in x.op_str))


def succs(addr):
    i = by.get(addr)
    if i is None:
        return []
    x = ins[i]
    out = []
    if is_branch(x) and x.operands and x.operands[0].type == ARM_OP_IMM:
        t = x.operands[0].imm
        if start <= t < end:
            out.append(t)
    if not terminates(x) and i + 1 < len(ins):
        out.append(ins[i + 1].address)
    return out


# predecessors of TARGET
preds = {}
for x in ins:
    for v in succs(x.address):
        preds.setdefault(v, []).append(x.address)

print("### predecessors of %#x: %s" % (TARGET, ["%#x" % p for p in preds.get(TARGET, [])]))


def last_sp_write(before, slot):
    """Walk back linearly from `before` to the previous store to [sp,#slot]."""
    i = by[before] - 1
    while i >= 0:
        x = ins[i]
        ops = x.operands
        if ops and len(ops) == 2 and x.mnemonic.startswith("str") and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            if mm.base == ARM_REG_SP and not mm.index and (mm.disp or 0) == slot:
                return x
        i -= 1
    return None


for slot in (0, 4, 8):
    w = last_sp_write(TARGET, slot)
    if w is not None:
        # find the register value written
        src = w.operands[0]
        j = by[w.address] - 1
        val = None
        while j >= 0 and val is None:
            y = ins[j]
            if y.operands and y.operands[0].type == src.type and \
                    getattr(y.operands[0], "reg", None) == getattr(src, "reg", None):
                if y.mnemonic in ("mov", "movs", "movw", "movt") and y.operands[-1].type == ARM_OP_IMM:
                    val = y.operands[-1].imm
                break
            j -= 1
        print("### [sp,#%d] last written at %#010x  (%s %s)  imm=%s"
              % (slot, w.address, w.mnemonic, w.op_str, hex(val) if val is not None else "?"))

# --- who uses the 'Arial-BoldMT' CFString @0x3a3570 -------------------------
txt = a.secs["__text"]
starts = a.starts()
OWN = {}
for cn, (c, i) in a.by_name.items():
    for mm in a.methods_of(c, i):
        if mm.imp:
            OWN.setdefault(mm.imp & ~1, "%s %s" % (cn, mm.selector))


def own(x):
    j = bisect.bisect_right(starts, x) - 1
    return "%s+%#x" % (OWN.get(starts[j], "?"), x - starts[j]) if j >= 0 else "?"


CF_ARIAL = 0x3A3570
hits = 0
regs = {}
for x in a.md.disasm(a.sl.data[txt.offset:txt.offset + txt.size], txt.addr):
    if not x.id or not x.operands:
        regs = {}
        continue
    ops = x.operands
    mm2 = x.mnemonic.split(".")[0]
    pc = x.address + 4
    pcw = (x.address + 4) & ~3
    dst = nv = None
    if mm2 == "add" and len(ops) >= 2 and ops[0].type == 1 and ops[1].type == 1 and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if isinstance(v, int):
            nv = (pc + v) & 0xFFFFFFFF
            dst = ops[0].reg
            if nv == CF_ARIAL:
                print("### CFSTR 'Arial-BoldMT' @%#x materialised at %#010x  %s" % (nv, x.address, own(x.address)))
                hits += 1
    elif mm2 == "ldr" and len(ops) == 2 and ops[0].type == 1 and ops[1].type == ARM_OP_MEM:
        m2 = ops[1].mem
        dst = ops[0].reg
        if m2.base == ARM_REG_PC:
            idx = regs.get(m2.index) if m2.index else 0
            if isinstance(idx, int):
                eff = (pcw + (m2.disp or 0) + idx) & 0xFFFFFFFF
                o = a.sl.addr_to_file(eff)
                nv = struct.unpack_from("<I", a.sl.data, o)[0] if o is not None else None
                if eff == CF_ARIAL or nv == CF_ARIAL:
                    print("### CFSTR 'Arial-BoldMT' @%#x via ldr at %#010x  %s" % (nv, x.address, own(x.address)))
                    hits += 1
        else:
            nv = None
    elif mm2 in ("movw", "movt") and ops[0].type == 1 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) if mm2 == "movt" else imm
        if nv == CF_ARIAL:
            print("### CFSTR 'Arial-BoldMT' via %s at %#010x  %s" % (mm2, x.address, own(x.address)))
            hits += 1
    elif mm2 in ("mov", "movs") and len(ops) >= 2 and ops[0].type == 1 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
        if nv == CF_ARIAL:
            print("### CFSTR 'Arial-BoldMT' via mov at %#010x  %s" % (x.address, own(x.address)))
            hits += 1
    elif mm2 == "mov" and len(ops) == 2 and ops[0].type == 1 and ops[1].type == 1:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
    elif mm2 in ("bl", "blx", "b"):
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)
        dst = None
    else:
        dst = None
    if dst is not None:
        regs[dst] = nv
print("### total CFSTR 'Arial-BoldMT' sites: %d" % hits)

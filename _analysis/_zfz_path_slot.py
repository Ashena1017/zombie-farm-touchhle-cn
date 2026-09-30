#!/usr/bin/env python3
"""Walk the SHORTEST path from ENTRY to TARGET inside one sub9 method and report,
at every store to a chosen stack slot, the constant value stored (if resolvable).

This settles what the 4th argument (stack[0] = table:) of
-[NSBundle localizedStringForKey:value:table:] is at a given call site.

Usage: python _analysis/_zfz_path_slot.py CLASS SELECTOR ENTRY TARGET SLOT
"""
from __future__ import annotations

import pathlib as _pl
import struct
import sys
from collections import deque

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_SP  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos[4:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL = pos[0], pos[1]
ENTRY, TARGET, SLOT = int(pos[2], 0), int(pos[3], 0), int(pos[4], 0)

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
ins = [x for x, _, _ in rows]
ann = {x.address: s for x, s, _ in rows}
by = {x.address: i for i, x in enumerate(ins)}


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


prev = {ENTRY: None}
q = deque([ENTRY])
while q:
    u = q.popleft()
    if u == TARGET:
        break
    for v in succs(u):
        if v not in prev:
            prev[v] = u
            q.append(v)
if TARGET not in prev:
    print("NOT REACHABLE")
    raise SystemExit(1)
path = [TARGET]
while path[-1] != ENTRY:
    path.append(prev[path[-1]])
path.reverse()

print("### shortest path %#x -> %#x : %d instructions" % (ENTRY, TARGET, len(path)))
print("\n### stores to [sp,#%#x] along this path:" % SLOT)
found = []
for ad in path:
    x = ins[by[ad]]
    ops = x.operands
    if not ops or len(ops) != 2 or not x.mnemonic.startswith("str") or ops[1].type != ARM_OP_MEM:
        continue
    mm = ops[1].mem
    if mm.base == ARM_REG_SP and not mm.index and (mm.disp or 0) == SLOT:
        # resolve the source register value by walking backwards from here
        src = ops[0]
        val = None
        j = by[ad] - 1
        while j >= 0:
            y = ins[j]
            if y.operands and y.operands[0].type == 1 and y.operands[0].reg == src.reg:
                if y.mnemonic in ("mov", "movs", "movw") and y.operands[-1].type == ARM_OP_IMM:
                    val = y.operands[-1].imm
                elif y.mnemonic == "movt" and y.operands[-1].type == ARM_OP_IMM:
                    val = (y.operands[-1].imm << 16) | ((val or 0) & 0xFFFF)
                break
            j -= 1
        found.append((ad, x, val))
        print("   %#010x  %-8s %-30s  imm=%s   %s"
              % (ad, x.mnemonic, x.op_str, hex(val) if val is not None else "?", ann[ad]))
if not found:
    print("   (none)")
    print("   -> the slot is NOT written on this path; it keeps whatever an earlier")
    print("      path segment wrote (possibly a caller-provided value).")

print("\n### last 26 instructions of the path")
for ad in path[-26:]:
    x = ins[by[ad]]
    print("   %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann[x.address]))

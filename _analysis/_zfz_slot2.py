#!/usr/bin/env python3
"""For a stack slot, list only the writes that lie on a path from ENTRY.

Usage: python _analysis/_zfz_slot2.py CLASS SELECTOR ENTRY SLOT [SLOT ...]
"""
from __future__ import annotations

import pathlib as _pl
import sys
from collections import deque

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_SP  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos[3:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL, ENTRY = pos[0], pos[1], int(pos[2], 0)
SLOTS = [int(x, 0) for x in pos[3:] if not x.lower().endswith(".ipa")]

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
ins = [x for x, _, _ in rows]
ann = {x.address: s for x, s, _ in rows}
by = {x.address: i for i, x in enumerate(ins)}
print("### %s -%s  %#x..%#x ; entry %#x" % (CLS, SEL, start, end, ENTRY))


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


seen, q = {ENTRY}, deque([ENTRY])
while q:
    u = q.popleft()
    for v in succs(u):
        if v not in seen:
            seen.add(v)
            q.append(v)
print("    %d instructions reachable from entry" % len(seen))

for S in SLOTS:
    print("\n### slot sp+%#x  (writes on the reachable set)" % S)
    for x in ins:
        if x.address not in seen:
            continue
        ops = x.operands
        if not ops or len(ops) != 2:
            continue
        if not x.mnemonic.startswith(("str", "ldr")):
            continue
        if ops[1].type != ARM_OP_MEM:
            continue
        mm = ops[1].mem
        if mm.base != ARM_REG_SP or mm.index or (mm.disp or 0) != S:
            continue
        kind = "WRITE" if x.mnemonic.startswith("str") else "read "
        print("   %s %#010x  %-8s %-34s %s" % (kind, x.address, x.mnemonic, x.op_str, ann[x.address]))

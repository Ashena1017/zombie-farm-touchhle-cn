#!/usr/bin/env python3
"""Walk a shortest path inside one sub9 method and print the tracked value of
selected registers/stack slots at each instruction.

Usage: python _analysis/_zfz_regpath.py CLASS SELECTOR --from A --to B --reg r10 --reg r4 --slot 0x84
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
from capstone.arm_const import ARM_OP_IMM  # noqa: E402
import capstone.arm_const as ac  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos[2:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL = pos[0], pos[1]
SRC = int(sys.argv[sys.argv.index("--from") + 1], 0)
DST = int(sys.argv[sys.argv.index("--to") + 1], 0)
REGS = [x for i, x in enumerate(sys.argv) if i and sys.argv[i - 1] == "--reg"]
SLOTS = [int(x, 0) for i, x in enumerate(sys.argv) if i and sys.argv[i - 1] == "--slot"]

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
ins = [x for x, _, _ in rows]
ann = {x.address: s for x, s, _ in rows}
regs_at = {x.address: r for x, _, r in rows}
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


prev = {SRC: None}
q = deque([SRC])
while q:
    u = q.popleft()
    for v in succs(u):
        if v not in prev:
            prev[v] = u
            q.append(v)
if DST not in prev:
    print("NOT REACHABLE")
    raise SystemExit(1)
path = [DST]
while path[-1] != SRC:
    path.append(prev[path[-1]])
path.reverse()

R = {getattr(ac, "ARM_REG_" + r.upper()): r for r in REGS}
print("### path %#x -> %#x (%d insns); watching regs=%s slots=%s"
      % (SRC, DST, len(path), REGS, [hex(s) for s in SLOTS]))
for p in path:
    i = by[p]
    x = ins[i]
    regs = regs_at[p]
    bits = []
    for rid, nm in R.items():
        v = regs.get(rid)
        bits.append("%s=%s" % (nm, ("%#x" % v) if isinstance(v, int) else "?"))
    print("  %#010x  %-8s %-40s %-28s %s"
          % (x.address, x.mnemonic, x.op_str, ann[x.address], " ".join(bits)))

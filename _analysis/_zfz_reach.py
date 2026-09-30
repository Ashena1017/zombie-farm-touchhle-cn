#!/usr/bin/env python3
"""Reachability inside one sub9 method: from a set of entry addresses, compute the
set of reachable instructions and answer 'is TARGET reachable from ENTRY?'.

Also prints the shortest path (as basic-block addresses) so the route is auditable.

Usage:
  python _analysis/_zfz_reach.py CLASS SELECTOR --from 0x27e92 --from 0x29498 --to 0x29b2e
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

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos[2:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL = pos[0], pos[1]
FROMS = [int(sys.argv[i + 1], 0) for i, x in enumerate(sys.argv) if x == "--from"]
TOS = [int(sys.argv[i + 1], 0) for i, x in enumerate(sys.argv) if x == "--to"]

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
ins = [x for x, _, _ in rows]
ann = {x.address: s for x, s, _ in rows}
print("### %s -%s  %#x..%#x (%d insns)" % (CLS, SEL, start, end, len(ins)))

by_addr = {x.address: i for i, x in enumerate(ins)}
UNCOND = ("b", "b.w")


def is_branch(x):
    mm = x.mnemonic
    return mm.startswith("b") and mm not in ("bic", "bfi", "bfc")


def terminates(x):
    if x.mnemonic in UNCOND or x.mnemonic.startswith("bx"):
        return True
    if x.mnemonic.startswith("pop") and "pc" in x.op_str:
        return True
    return False


def targets(x):
    out = []
    if is_branch(x) and x.operands and x.operands[0].type == ARM_OP_IMM:
        t = x.operands[0].imm
        if start <= t < end:
            out.append(t)
    return out


def succs(addr):
    i = by_addr.get(addr)
    if i is None:
        return []
    x = ins[i]
    out = list(targets(x))
    if not terminates(x) and i + 1 < len(ins):
        out.append(ins[i + 1].address)
    return out


for f in FROMS:
    seen = {f}
    prev = {}
    q = deque([f])
    while q:
        u = q.popleft()
        for v in succs(u):
            if v not in seen:
                seen.add(v)
                prev[v] = u
                q.append(v)
    print("\n### from %#x : %d instructions reachable" % (f, len(seen)))
    for t in TOS:
        ok = t in seen
        print("    -> %#x reachable? %s" % (t, "YES" if ok else "NO"))
        if ok:
            path = [t]
            while path[-1] != f:
                path.append(prev[path[-1]])
            path.reverse()
            print("       path: " + " -> ".join("%#x" % p for p in path[:40])
                  + (" ..." if len(path) > 40 else ""))

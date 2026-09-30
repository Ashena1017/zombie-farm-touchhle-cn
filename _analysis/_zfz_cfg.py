#!/usr/bin/env python3
"""Basic-block CFG + backward slice for one ObjC method of the ZFR binary (sub9).

Finds the basic block containing TARGET, walks predecessors backwards and prints
the cone of blocks that can reach it, so the guarding condition is visible.

Usage:
  python _analysis/_zfz_cfg.py CLASS SELECTOR TARGET [ipa] [--depth=N] [--blocks]
"""
from __future__ import annotations

import pathlib as _pl
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
opts = {x.split("=")[0]: x.split("=")[1] for x in sys.argv[1:] if x.startswith("--") and "=" in x}
DEPTH = int(opts.get("--depth", 6))
IPA = pos[3] if len(pos) > 3 else str(
    ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
CLS, SEL, TARGET = pos[0], pos[1], int(pos[2], 0)

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
ins = [x for x, _, _ in rows]
ann = {x.address: s for x, s, _ in rows}
print("### %s -%s  %#x..%#x (%d insns)" % (CLS, SEL, start, end, len(ins)))

UNCOND = ("b", "b.w")
RET = ("bx", "pop")


def is_branch(x):
    mnem = x.mnemonic
    return mnem.startswith("b") and mnem not in ("bic", "bfi", "bfc")


def is_cond_branch(x):
    mnem = x.mnemonic
    return is_branch(x) and mnem not in UNCOND


def terminates(x):
    """True if control never falls through to the next instruction."""
    if x.mnemonic in UNCOND:
        return True
    if x.mnemonic.startswith("bx"):
        return True
    if x.mnemonic.startswith("pop") and "pc" in x.op_str:
        return True
    if x.mnemonic in ("b",) and x.op_str.strip().startswith("#"):
        return True
    return False


# ---- leaders ---------------------------------------------------------------
leaders = {start}
for i, x in enumerate(ins):
    if is_branch(x) and x.operands and x.operands[0].type == ARM_OP_IMM:
        t = x.operands[0].imm
        if start <= t < end:
            leaders.add(t)
    if (is_branch(x) or terminates(x)) and i + 1 < len(ins):
        leaders.add(ins[i + 1].address)
L = sorted(leaders)
blocks = []
for i, lo in enumerate(L):
    hi = L[i + 1] if i + 1 < len(L) else end
    blocks.append((lo, hi))
idx_of = {lo: i for i, (lo, hi) in enumerate(blocks)}


def body(b):
    lo, hi = b
    return [x for x in ins if lo <= x.address < hi]


def blk_containing(addr):
    for b in blocks:
        if b[0] <= addr < b[1]:
            return b
    return None


# ---- successors ------------------------------------------------------------
succ = {}
for i, b in enumerate(blocks):
    bs = body(b)
    out = []
    for x in bs:
        if is_branch(x) and x.operands and x.operands[0].type == ARM_OP_IMM:
            t = x.operands[0].imm
            tb = blk_containing(t)
            if tb and tb not in out:
                out.append(tb)
    last = bs[-1] if bs else None
    if last is not None and not terminates(last) and i + 1 < len(blocks):
        out.append(blocks[i + 1])
    succ[b] = out

pred = {b: [] for b in blocks}
for b, outs in succ.items():
    for o in outs:
        pred[o].append(b)


def show(b, tag=""):
    print("\n---- block %#x..%#x %s ----" % (b[0], b[1], tag))
    for x in body(b):
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann[x.address]))


tb = blk_containing(TARGET)
print("### TARGET %#x -> block %#x..%#x" % (TARGET, tb[0], tb[1]))

# ---- BFS backwards ---------------------------------------------------------
seen, frontier = set(), [tb]
for lvl in range(DEPTH):
    nxt = []
    for b in frontier:
        if b in seen:
            continue
        seen.add(b)
        for p in pred[b]:
            if p not in seen:
                nxt.append(p)
    if not nxt:
        break
    frontier = nxt

print("\n### backward cone: %d blocks" % len(seen))
if "--blocks" in sys.argv:
    for b in sorted(seen):
        show(b)
else:
    show(tb, "(TARGET)")
    for b in sorted(seen):
        if b != tb:
            show(b)

#!/usr/bin/env python3
"""CFG-aware view of the 'Fertilized by %@!' float site in sub9
ZFToolManager -popGameActionAndExecute:deltaTime:

* annotates the WHOLE method (so register tracking is valid at the site)
* prints a window around the float
* lists every branch that targets the float block, plus its owning block
  (so we can see the guarding condition)

Usage: python _analysis/_zfz_fertile_cfg.py [ipa] [lo] [hi]
"""
from __future__ import annotations

import bisect
import pathlib as _pl
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_REG_PC  # noqa: E402

IPA = sys.argv[1] if len(sys.argv) > 1 else str(
    ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
LO = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x29e00
HI = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x2a260

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range("ZFToolManager", "popGameActionAndExecute:deltaTime:")
rows = a.annotate(a.disasm(start, end))
print("### %s -%s  %#x..%#x (%d insns)" % ("ZFToolManager", m.selector, start, end, len(rows)))

addr2idx = {x.address: i for i, (x, _, _) in enumerate(rows)}
starts = a.starts()


def owner(addr):
    i = bisect.bisect_right(starts, addr) - 1
    if i < 0:
        return "?"
    for cn, (c, info) in a.by_name.items():
        for mm in a.methods_of(c, info):
            if mm.imp and (mm.imp & ~1) == starts[i]:
                return "%s [%s] %s+%#x" % (cn, mm.kind, mm.selector, addr - starts[i])
    return "%#x+?" % starts[i]


# --- 1. print the window ----------------------------------------------------
print("\n### window %#x..%#x" % (LO, HI))
for x, ann, _ in rows:
    if LO <= x.address < HI:
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))

# --- 2. every branch whose target is inside the window ----------------------
print("\n### branches INTO %#x..%#x (from anywhere in the method)" % (LO, HI))
for x, ann, _ in rows:
    if not x.mnemonic.startswith("b"):
        continue
    if not x.operands or x.operands[0].type != ARM_OP_IMM:
        continue
    t = x.operands[0].imm
    if LO <= t < HI:
        print("  %#010x  %-8s %-30s -> %#x      from %s"
              % (x.address, x.mnemonic, x.op_str, t, owner(x.address)))

# --- 3. linear predecessors of the window (the fall-through) ----------------
idx = next((i for i, (x, _, _) in enumerate(rows) if x.address >= LO), None)
print("\n### 12 instructions before %#x" % LO)
for x, ann, _ in rows[max(0, idx - 12):idx]:
    print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))

# --- 4. what happens right after the window ---------------------------------
print("\n### instructions %#x..%#x" % (HI, HI + 0x120))
for x, ann, _ in rows:
    if HI <= x.address < HI + 0x120:
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))

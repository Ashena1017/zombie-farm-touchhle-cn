#!/usr/bin/env python3
"""List every conditional branch in [LO,HI) of a sub9 method whose target lies
OUTSIDE [LO,HI) -- i.e. potential 'skip this region' edges.

Usage: python _analysis/_zfz_escapes.py CLASS SELECTOR LO HI [ipa]
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
IPA = next((x for x in pos[4:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL, LO, HI = pos[0], pos[1], int(pos[2], 0), int(pos[3], 0)

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
print("### %s -%s  %#x..%#x ; region %#x..%#x" % (CLS, SEL, start, end, LO, HI))

print("\n### branches inside the region")
for x, ann, _ in rows:
    if not (LO <= x.address < HI):
        continue
    if not x.mnemonic.startswith("b") or not x.operands:
        continue
    if x.operands[0].type != ARM_OP_IMM:
        continue
    t = x.operands[0].imm
    tag = "OUTSIDE" if not (LO <= t < HI) else "inside "
    print("   %#010x  %-8s %-28s -> %#010x  %s" % (x.address, x.mnemonic, x.op_str, t, tag))

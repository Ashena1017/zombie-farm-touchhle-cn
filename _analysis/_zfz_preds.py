#!/usr/bin/env python3
"""Who branches to ADDR inside a method, and where does the case body start?

Usage: python _analysis/_zfz_preds.py CLASS SELECTOR ADDR [ipa]
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
IPA = next((x for x in pos[2:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL = pos[0], pos[1]
TARGETS = [int(x, 0) for x in pos[2:] if not x.lower().endswith(".ipa")]

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
print("### %s -%s  %#x..%#x" % (CLS, SEL, start, end))

for T in TARGETS:
    print("\n### who jumps to %#x ?" % T)
    for x, ann, _ in rows:
        if x.mnemonic.startswith("b") and x.operands and x.operands[0].type == ARM_OP_IMM:
            if x.operands[0].imm == T:
                print("   %#010x  %-8s %-30s %s" % (x.address, x.mnemonic, x.op_str, ann))

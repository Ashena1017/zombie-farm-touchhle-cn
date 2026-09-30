#!/usr/bin/env python3
"""Find every read/write of a given stack slot inside one sub9 method.

Usage: python _analysis/_zfz_slot.py CLASS SELECTOR 0x68 0x6c 0x8c [ipa]
"""
from __future__ import annotations

import pathlib as _pl
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_MEM, ARM_REG_SP  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos[2:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL = pos[0], pos[1]
SLOTS = [int(x, 0) for x in pos[2:] if not x.lower().endswith(".ipa")]

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
print("### %s -%s  %#x..%#x" % (CLS, SEL, start, end))

for S in SLOTS:
    print("\n### stack slot sp+%#x" % S)
    for i, (x, ann, _) in enumerate(rows):
        ops = x.operands
        if not ops:
            continue
        # store
        if x.mnemonic.startswith("str") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            if mm.base == ARM_REG_SP and not mm.index and (mm.disp or 0) == S:
                ctx = []
                for j in range(max(0, i - 6), i):
                    px, pann, _ = rows[j]
                    ctx.append("        .. %#010x %-8s %-34s %s" % (px.address, px.mnemonic, px.op_str, pann))
                print("   WRITE %#010x  %-8s %-34s %s" % (x.address, x.mnemonic, x.op_str, ann))
                for c in ctx[-4:]:
                    print(c)
        if x.mnemonic.startswith("ldr") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            if mm.base == ARM_REG_SP and not mm.index and (mm.disp or 0) == S:
                print("   read  %#010x  %-8s %-34s %s" % (x.address, x.mnemonic, x.op_str, ann))

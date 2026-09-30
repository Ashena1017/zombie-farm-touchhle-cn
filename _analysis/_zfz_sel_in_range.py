#!/usr/bin/env python3
"""Resolve the 3 objc_msgSend selectors inside a small range, so we can read what
CCLabel +labelWithString:fontName:fontSize: actually does.

Usage: python _analysis/_zfz_sel_in_range.py LO HI
"""
from __future__ import annotations

import pathlib as _pl
import struct
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
from _t6_ann import Annotator, load  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
LO, HI = int(sys.argv[1], 0), int(sys.argv[2], 0)

a = Annotator(load(IPA, subtype=9))
print("### selrefs referenced in %#x..%#x" % (LO, HI))
for x, ann, _ in a.annotate(a.disasm(LO, HI)):
    if "SEL " in ann or "CFSTR" in ann or "MSG" in ann:
        print("   %#010x  %-8s %-38s %s" % (x.address, x.mnemonic, x.op_str, ann))

# raw: decode every ldr rX,[pc,#imm] + add rX,pc pair in the range to a selref name
print("\n### raw delta-idiom resolution")
regs = {}
for x, _, _ in a.annotate(a.disasm(LO, HI)):
    pass
import capstone  # noqa: E402
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
md.detail = True
md.skipdata = True
o = a.sl.addr_to_file(LO)
for x in md.disasm(a.sl.data[o:o + (HI - LO)], LO):
    ops = x.operands
    if not ops:
        continue
    note = ""
    if x.mnemonic == "ldr" and len(ops) == 2 and ops[1].type == capstone.arm_const.ARM_OP_MEM \
            and ops[1].mem.base == capstone.arm_const.ARM_REG_PC:
        eff = ((x.address + 4) & ~3) + (ops[1].mem.disp or 0)
        oo = a.sl.addr_to_file(eff)
        v = struct.unpack_from("<I", a.sl.data, oo)[0] if oo else None
        note = "ldr from %#x = %s" % (eff, hex(v) if v is not None else "?")
        if eff in a.sel_at:
            note += "  SEL %r" % a.sel_at[eff]
        elif v in a.sel_cstr:
            note += "  SEL %r" % a.sel_cstr[v]
    print("   %#010x  %-8s %-34s %s" % (x.address, x.mnemonic, x.op_str, note))

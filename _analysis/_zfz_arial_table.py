#!/usr/bin/env python3
"""Find every site in sub9 that stores the CFString 'Arial-BoldMT' (@0x3a3570)
into a stack slot -- i.e. passes it as the `table:` argument (3rd arg, stack[0])
of -[NSBundle localizedStringForKey:value:table:].

Usage: python _analysis/_zfz_arial_table.py
"""
from __future__ import annotations

import bisect
import pathlib as _pl
import struct
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC, ARM_REG_SP  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
ARIAL = 0x3A3570

a = Annotator(load(IPA, subtype=9))
txt = a.secs["__text"]
starts = a.starts()
OWN = {}
for cn, (c, i) in a.by_name.items():
    for mm in a.methods_of(c, i):
        if mm.imp:
            OWN.setdefault(mm.imp & ~1, "%s %s" % (cn, mm.selector))


def own(x):
    j = bisect.bisect_right(starts, x) - 1
    return "%s+%#x" % (OWN.get(starts[j], "?"), x - starts[j]) if j >= 0 else "?"


# also collect all CFStrings so we can name any stack-stored pointer
cs = {}
for sec in a.sl.sections:
    if sec.name != "__cstring":
        continue
    blob = a.sl.data[sec.offset:sec.offset + sec.size]
    p = 0
    while p < len(blob):
        e = blob.find(b"\0", p)
        if e < 0:
            break
        try:
            cs[sec.addr + p] = blob[p:e].decode("utf-8")
        except Exception:  # noqa: BLE001
            pass
        p = e + 1
CF = {}
for sec in a.sl.sections:
    if sec.name not in ("__cfstring", "__objc_cfstring"):
        continue
    for off in range(0, sec.size, 4):
        ad = sec.addr + off
        o = a.sl.addr_to_file(ad)
        if o is None or o + 16 > len(a.sl.data):
            continue
        isa, fl, d, ln = struct.unpack_from("<IIII", a.sl.data, o)
        if not (0x7C0 <= fl <= 0x7FF) or ln > 4096:
            continue
        s = cs.get(d)
        if s is not None:
            CF[ad] = s

regs = {}
for x in a.md.disasm(a.sl.data[txt.offset:txt.offset + txt.size], txt.addr):
    if not x.id or not x.operands:
        regs = {}
        continue
    ops = x.operands
    m = x.mnemonic.split(".")[0]
    pc = x.address + 4
    pcw = (x.address + 4) & ~3
    dst = nv = None
    if m == "add" and len(ops) >= 2 and ops[0].type == 1 and ops[1].type == 1 and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if isinstance(v, int):
            nv = (pc + v) & 0xFFFFFFFF
            dst = ops[0].reg
    elif m == "ldr" and len(ops) == 2 and ops[0].type == 1 and ops[1].type == ARM_OP_MEM:
        m2 = ops[1].mem
        dst = ops[0].reg
        if m2.base == ARM_REG_PC:
            idx = regs.get(m2.index) if m2.index else 0
            if isinstance(idx, int):
                eff = (pcw + (m2.disp or 0) + idx) & 0xFFFFFFFF
                o = a.sl.addr_to_file(eff)
                nv = struct.unpack_from("<I", a.sl.data, o)[0] if o is not None else None
        else:
            nv = None
    elif m in ("movw", "movt") and ops[0].type == 1 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) if m == "movt" else imm
    elif m in ("mov", "movs") and len(ops) >= 2 and ops[0].type == 1 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
    elif m == "mov" and len(ops) == 2 and ops[0].type == 1 and ops[1].type == 1:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
    elif m.startswith("str") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        if mm.base == ARM_REG_SP and not mm.index:
            src = regs.get(ops[0].reg)
            if isinstance(src, int) and src in CF:
                print("STORE-TO-STACK %#010x  %-8s %-30s [sp,#%#x] = CFSTR %r   %s"
                      % (x.address, x.mnemonic, x.op_str, mm.disp or 0, CF[src], own(x.address)))
            elif src == ARIAL:
                print("*** ARIAL AS TABLE at %#010x  [sp,#%#x]   %s"
                      % (x.address, mm.disp or 0, own(x.address)))
        dst = None
    elif m in ("bl", "blx", "b"):
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)
        dst = None
    else:
        dst = None
    if dst is not None:
        regs[dst] = nv

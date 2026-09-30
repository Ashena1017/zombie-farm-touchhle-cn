#!/usr/bin/env python3
"""Which CFStrings are used as the `table:` argument of
localizedStringForKey:value:table: in sub9?

Resolves r3 at every such objc_msgSend and tallies the CFString used.

Usage: python _analysis/_zfz_table_arg.py
"""
from __future__ import annotations

import bisect
import collections
import pathlib as _pl
import struct
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
a = Annotator(load(IPA, subtype=9))

# cstring -> addr map
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

# all CFString objects
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

starts = a.starts()
OWN = {}
for cn, (c, i) in a.by_name.items():
    for mm in a.methods_of(c, i):
        if mm.imp:
            OWN.setdefault(mm.imp & ~1, "%s %s" % (cn, mm.selector))


def own(x):
    j = bisect.bisect_right(starts, x) - 1
    return "%s+%#x" % (OWN.get(starts[j], "?"), x - starts[j]) if j >= 0 else "?"


txt = a.secs["__text"]
md = a.md
regs = {}
tally = collections.Counter()
sites = []
for x in md.disasm(a.sl.data[txt.offset:txt.offset + txt.size], txt.addr):
    if not x.id or not x.operands:
        regs = {}
        continue
    ops = x.operands
    m = x.mnemonic.split(".")[0]
    pc = x.address + 4
    pcw = (x.address + 4) & ~3
    dst = nv = None
    if m == "add" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and \
            ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if isinstance(v, int):
            nv = (pc + v) & 0xFFFFFFFF
            dst = ops[0].reg
    elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        dst = ops[0].reg
        if mm.base == ARM_REG_PC:
            idx = regs.get(mm.index) if mm.index else 0
            if isinstance(idx, int):
                eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                o = a.sl.addr_to_file(eff)
                nv = struct.unpack_from("<I", a.sl.data, o)[0] if o is not None else None
        else:
            nv = None
    elif m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) if m == "movt" else imm
    elif m in ("mov", "movs") and len(ops) >= 2 and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
    elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
    elif m in ("bl", "blx", "b"):
        if m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM and \
                (ops[0].imm & ~1) == 0x2D014C:
            r1v = regs.get(67)  # r1
            nm = None
            if isinstance(r1v, int):
                o = a.sl.addr_to_file(r1v)
                if o is not None:
                    p = struct.unpack_from("<I", a.sl.data, o)[0]
                    nm = cs.get(p)
            if nm == "localizedStringForKey:value:table:":
                r3v = regs.get(69)  # r3
                tbl = CF.get(r3v) if isinstance(r3v, int) else None
                key = CF.get(regs.get(68)) if isinstance(regs.get(68), int) else None
                tally[tbl] += 1
                sites.append((x.address, key, tbl, own(x.address)))
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)
        dst = None
    else:
        dst = None
    if dst is not None:
        regs[dst] = nv

print("### table: argument census for localizedStringForKey:value:table: (%d sites)" % len(sites))
for t, n in tally.most_common(20):
    print("   %-24r %d" % (t, n))

print("\n### sites where table == 'Arial-BoldMT'")
for ad, key, tbl, o in sites:
    if tbl == "Arial-BoldMT":
        print("   %#010x  key=%-40r  %s" % (ad, key, o))

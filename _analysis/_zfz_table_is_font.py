#!/usr/bin/env python3
"""Does any sub9 method pass a FONT NAME as the `table:` argument of
-[NSBundle localizedStringForKey:value:table:] ?

Scans every objc_msgSend to that selector, resolves the `table:` argument
(stack[0]) by walking back to the nearest [sp] store, and reports any table that
is NOT nil/empty.

Usage: python _analysis/_zfz_table_is_font.py
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
from capstone.arm_const import ARM_OP_MEM, ARM_REG_SP  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
a = Annotator(load(IPA, subtype=9))

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
rows = a.annotate(a.disasm(txt.addr, txt.addr + txt.size))
tally = collections.Counter()
interesting = []
for i, (x, ann, regs) in enumerate(rows):
    if not ann.startswith("MSG localizedStringForKey:value:table:"):
        continue
    key = CF.get(regs.get(68)) if isinstance(regs.get(68), int) else None
    val = CF.get(regs.get(69)) if isinstance(regs.get(69), int) else None
    tbl = "<no store found in 60 insns>"
    for j in range(i - 1, max(0, i - 60), -1):
        y = rows[j][0]
        ops = y.operands
        if ops and len(ops) == 2 and y.mnemonic.startswith("str") and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            if mm.base == ARM_REG_SP and not mm.index and (mm.disp or 0) == 0:
                v = rows[j][2].get(ops[0].reg)
                if isinstance(v, int) and v in CF:
                    tbl = CF[v]
                elif isinstance(v, int):
                    tbl = "ptr %#x" % v
                else:
                    tbl = "reg (unresolved)"
                break
    tally[tbl] += 1
    if tbl not in ("", "<no store found in 60 insns>"):
        interesting.append((x.address, key, val, tbl, own(x.address)))

print("### table: argument census (%d sites total)" % sum(tally.values()))
for t, n in tally.most_common(20):
    print("   %-42r %d" % (t, n))
print("\n### sites whose table is NOT the empty string (%d)" % len(interesting))
for ad, key, val, tbl, o in interesting[:40]:
    print("   %#010x  table=%-16r key=%-34r value=%-14r %s" % (ad, tbl, key, val, o))

#!/usr/bin/env python3
"""Global objc_msgSend site scanner for sub9: report every call site of the given
selectors anywhere in __text, with the owning method.

Usage: python _analysis/_zfz_sel_sites.py SEL [SEL ...]
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

IPA = next((x for x in sys.argv[1:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
WANT = {x for x in sys.argv[1:] if not x.lower().endswith(".ipa")}

a = Annotator(load(IPA, subtype=9))
starts = a.starts()
OWNER = {}
for cn, (c, info) in a.by_name.items():
    for mm in a.methods_of(c, info):
        if mm.imp:
            OWNER.setdefault(mm.imp & ~1, "%s [%s] %s" % (cn, mm.kind, mm.selector))


def owner(addr):
    i = bisect.bisect_right(starts, addr) - 1
    if i < 0:
        return "?"
    return "%s+%#x" % (OWNER.get(starts[i], "?"), addr - starts[i])


txt = a.secs["__text"]
rows = a.annotate(a.disasm(txt.addr, txt.addr + txt.size))
print("### %d instructions scanned; looking for %r" % (len(rows), sorted(WANT)))
for i, (x, ann, _) in enumerate(rows):
    if not ann.startswith("MSG "):
        continue
    name = ann[4:].split("(", 1)[0]
    if name not in WANT:
        continue
    print("\n   %#010x  %s" % (x.address, owner(x.address)))
    print("        %s" % ann)
    for j in range(max(0, i - 10), i):
        px, pann, _ = rows[j]
        print("        .. %#010x  %-8s %-32s %s" % (px.address, px.mnemonic, px.op_str, pann))

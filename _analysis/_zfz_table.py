#!/usr/bin/env python3
"""Who references the cstring 'Arial-BoldMT' in sub9, and is it the table arg of
localizedStringForKey:value:table: ?
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

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
a = Annotator(load(IPA, subtype=9))

targets = {}
for sec in a.sl.sections:
    if sec.name != "__cstring":
        continue
    blob = a.sl.data[sec.offset:sec.offset + sec.size]
    p = 0
    while p < len(blob):
        e = blob.find(b"\0", p)
        if e < 0:
            break
        s = blob[p:e]
        if b"Arial-BoldMT" in s:
            targets[sec.addr + p] = s.decode("utf-8", "replace")
        p = e + 1
print("cstring candidates: %s" % {hex(k): v for k, v in targets.items()})

starts = a.starts()
OWNER = {}
for cn, (c, info) in a.by_name.items():
    for mm in a.methods_of(c, info):
        if mm.imp:
            OWNER.setdefault(mm.imp & ~1, "%s [%s] %s" % (cn, mm.kind, mm.selector))


def owner(addr):
    i = bisect.bisect_right(starts, addr) - 1
    return "%s+%#x" % (OWNER.get(starts[i], "?"), addr - starts[i]) if i >= 0 else "?"


txt = a.secs["__text"]
rows = a.annotate(a.disasm(txt.addr, txt.addr + txt.size))
print("\n### code sites materialising them")
for i, (x, ann, _) in enumerate(rows):
    if any(hex(t) in ann for t in targets) or "Arial-BoldMT" in ann:
        print("   %#010x  %-8s %-40s %s   %s"
              % (x.address, x.mnemonic, x.op_str, ann, owner(x.address)))
        for j in range(i, min(i + 8, len(rows))):
            px, pann, _ = rows[j]
            if pann.startswith("MSG "):
                print("        -> %#010x %s" % (px.address, pann))
                break

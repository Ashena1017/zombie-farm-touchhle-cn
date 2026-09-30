#!/usr/bin/env python3
"""Dump the neighborhood of the 'Fertilized by %@!' float site inside
ZFToolManager -popGameActionAndExecute:deltaTime: (sub9), plus a selector-usage
sweep for the fertilize family.

Usage: python _analysis/_zfz_fertile_site.py [ipa]
"""
from __future__ import annotations

import pathlib as _pl
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

from _t6_ann import Annotator, load  # noqa: E402

IPA = sys.argv[1] if len(sys.argv) > 1 else str(
    ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")

a = Annotator(load(IPA, subtype=9))

print("### method boundaries for ZFToolManager -popGameActionAndExecute:deltaTime:")
m, start, end = a.method_range("ZFToolManager", "popGameActionAndExecute:deltaTime:")
print("    imp=%#x range=%#x..%#x  (len %#x)" % (m.imp, start, end, end - start))

# The float site: 0x2a0d0 materialises 'Fertilized by %@!' , msgSend at 0x2a0dc.
print("\n### window around the float site (0x2a000..0x2a140)")
a.dump_range(0x2a000, 0x2a140)

print("\n### full method dump -> _analysis/dumps/_zfz_toolmgr.txt")
rows = a.annotate(a.disasm(start, end))
with open(ROOT / "_analysis/dumps/_zfz_toolmgr.txt", "w", encoding="utf-8") as f:
    for x, ann, _ in rows:
        f.write("  %#010x  %-8s %-42s %s\n" % (x.address, x.mnemonic, x.op_str, ann))
print("    wrote %d instructions" % len(rows))

# ---- who sends the fertilize selectors -------------------------------------
print("\n### selector usage sweep (whole __text of sub9)")
WANT = {
    "fertilizeTile:", "unFertilizeTile:", "fertilized", "setFertilized:",
    "timesFertilized", "setTimesFertilized:", "check100Fertilize",
    "fertilizeChance",
}
txt = a.secs["__text"]
ins = a.annotate(a.disasm(txt.addr, txt.addr + txt.size))
starts = a.starts()
import bisect  # noqa: E402


def owner(addr):
    i = bisect.bisect_right(starts, addr) - 1
    if i < 0:
        return "?"
    for cn, (c, info) in a.by_name.items():
        for mm in a.methods_of(c, info):
            if mm.imp and (mm.imp & ~1) == starts[i]:
                return "%s [%s] %s+%#x" % (cn, mm.kind, mm.selector, addr - starts[i])
    return "%#x+?" % starts[i]


for x, ann, _ in ins:
    if not ann.startswith("MSG "):
        continue
    name = ann[4:].split("(", 1)[0]
    if name in WANT:
        print("   %#010x  %-70s  %s" % (x.address, ann, owner(x.address)))

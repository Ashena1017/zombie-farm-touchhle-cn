#!/usr/bin/env python3
"""Market.plist subCategory/category census + TileProperties keys touching soil."""
from __future__ import annotations

import collections
import pathlib as _pl
import plistlib
import sys
import zipfile

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")

z = zipfile.ZipFile(IPA)
m = plistlib.loads(z.read("Payload/ZFR.app/Market.plist"))
c = collections.Counter((e.get("category"), e.get("subCategory")) for e in m if isinstance(e, dict))
print("== Market.plist (category, subCategory) census ==")
for k, v in sorted(c.items(), key=lambda x: str(x[0])):
    print("   %-24s %d" % (str(k), v))

print("\n== examples ==")
seen = set()
for e in m:
    if not isinstance(e, dict):
        continue
    k = (e.get("category"), e.get("subCategory"))
    if k in seen:
        continue
    seen.add(k)
    print("   %-30s %s" % (str(k), {kk: vv for kk, vv in e.items() if kk in
                                    ("name", "unitKey", "subCategory", "category", "info", "cost", "level")}))

print("\n== Market entries whose 'name' is a garden zombie ==")
for e in m:
    if isinstance(e, dict) and str(e.get("unitKey", "")).startswith("ZombieActorGarden"):
        print("   %s" % e)

tp = plistlib.loads(z.read("Payload/ZFR.app/TileProperties.plist"))
print("\n== TileProperties entries mentioning fertil/seed/soil (keys) ==")
for k, v in tp.items():
    ks = str(k)
    vs = repr(v)
    if "fertil" in ks.lower() or "fertil" in vs.lower():
        print("   %s -> %s" % (k, vs[:300]))
print("   total TileProperties entries: %d" % len(tp))
seeded = [k for k in tp if "seed" in str(k).lower()]
print("   entries with 'seed' in key: %d  e.g. %s" % (len(seeded), seeded[:8]))
soil = [k for k in tp if str(k).lower().startswith("soil")]
print("   entries starting with 'soil': %d  e.g. %s" % (len(soil), soil[:12]))

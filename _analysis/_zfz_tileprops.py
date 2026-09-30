#!/usr/bin/env python3
"""TileProperties.plist: dump entries relevant to zombie/plant soil + canHarvest."""
from __future__ import annotations

import pathlib as _pl
import plistlib
import sys
import zipfile

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")

z = zipfile.ZipFile(IPA)
tp = plistlib.loads(z.read("Payload/ZFR.app/TileProperties.plist"))

WANT = ["soil_seeded_garden_zombie", "soil_germinating_garden_zombie",
        "soil_seeded_carrots", "soil_germinating_carrots",
        "soil_barren", "soil_plowed", "soil_blighted", "soil_seeded_bombie",
        "soil_germinating_bombie"]
for k in WANT:
    if k in tp:
        print("== %s ==\n   %s" % (k, tp[k]))
    else:
        print("== %s == MISSING" % k)

print("\n== distinct key sets among soil_seeded_* ==")
import collections  # noqa: E402
c = collections.Counter()
for k, v in tp.items():
    if str(k).startswith("soil_seeded_") or str(k).startswith("soil_germinating_"):
        c[tuple(sorted(v.keys()))] += 1
for ks, n in c.most_common():
    print("   %3d x %s" % (n, ks))

print("\n== which soil_seeded_* have canHarvest false ==")
n = 0
for k, v in tp.items():
    if str(k).startswith("soil_seeded_") or str(k).startswith("soil_germinating_"):
        if v.get("canHarvest") in (False, 0):
            n += 1
            if n <= 25:
                print("   %-46s canHarvest=%r name=%r" % (k, v.get("canHarvest"), v.get("name")))
print("   ... total %d" % n)

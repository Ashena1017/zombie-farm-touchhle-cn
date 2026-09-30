#!/usr/bin/env python3
"""TileProperties.plist: canHarvest census + full transform chain for a zombie."""
from __future__ import annotations

import pathlib as _pl
import plistlib
import zipfile

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")

z = zipfile.ZipFile(IPA)
tp = plistlib.loads(z.read("Payload/ZFR.app/TileProperties.plist"))

ch = [(k, v) for k, v in tp.items() if "canHarvest" in v]
print("entries with canHarvest: %d" % len(ch))
for k, v in ch[:20]:
    print("   %-44s %s" % (k, {kk: vv for kk, vv in v.items() if kk in ("name", "canHarvest", "transformsTo")}))

print("\nfull transform chain from soil_seeded_garden_zombie:")
k = "soil_seeded_garden_zombie"
seen = []
while k and k in tp and k not in seen:
    seen.append(k)
    print("   %-46s %s" % (k, {kk: vv for kk, vv in tp[k].items() if kk in ("name", "canHarvest", "transformsTo", "plowable")}))
    k = tp[k].get("transformsTo")

print("\nfull transform chain from soil_seeded_carrots:")
k = "soil_seeded_carrots"
seen = []
while k and k in tp and k not in seen:
    seen.append(k)
    print("   %-46s %s" % (k, {kk: vv for kk, vv in tp[k].items() if kk in ("name", "canHarvest", "transformsTo", "plowable")}))
    k = tp[k].get("transformsTo")

print("\nall keys seen across TileProperties:")
ks = set()
for v in tp.values():
    ks |= set(v.keys())
print("   %s" % sorted(ks))

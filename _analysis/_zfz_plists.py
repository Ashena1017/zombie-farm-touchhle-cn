#!/usr/bin/env python3
"""Inspect ZFR data plists: which entries carry fertilizer / zombie / plant keys.

Usage: python _analysis/_zfz_plists.py [key ...]
"""
from __future__ import annotations

import pathlib as _pl
import plistlib
import sys
import zipfile

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
KEYS = sys.argv[1:] or ["fertilizeChance", "fertiliz", "isZombie", "zombie"]

z = zipfile.ZipFile(IPA)
for name in ("Payload/ZFR.app/Market.plist", "Payload/ZFR.app/TileProperties.plist",
             "Payload/ZFR.app/UnitStats.plist", "Payload/ZFR.app/ZombieNames.plist"):
    try:
        d = plistlib.loads(z.read(name))
    except Exception as e:  # noqa: BLE001
        print("%s: %s" % (name, e))
        continue
    print("\n===== %s  (root type %s, %d entries) =====" % (
        name.split("/")[-1], type(d).__name__, len(d)))
    if isinstance(d, dict):
        items = list(d.items())[:400]
    elif isinstance(d, list):
        items = list(enumerate(d))[:400]
    else:
        items = []
    for k, v in items:
        blob = repr(v)
        if any(x.lower() in blob.lower() for x in KEYS) or any(x.lower() in str(k).lower() for x in KEYS):
            print("  %-34s %s" % (k, blob[:400]))

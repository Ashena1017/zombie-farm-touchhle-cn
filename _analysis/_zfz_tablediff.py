#!/usr/bin/env python3
"""Compare the `Fertilized by %@!` value in BOTH string tables across the IPA lineage.

This settles which table the fertilize float actually reads:
if Localizable.strings was always correct while Arial-BoldMT.strings was mojibake,
and the user saw mojibake, the float reads Arial-BoldMT.strings.
"""
from __future__ import annotations

import pathlib as _pl
import plistlib
import zipfile

ROOT = next(p for p in [_pl.Path(__file__).resolve().parent, *_pl.Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())

KEY = "Fertilized by %@!"
VERSIONS = [
    "ZFR 1.0.zh-CN-unsigned.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v15fix.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v18fix.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa",
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa",
]
TABLES = [
    "Payload/ZFR.app/zh-Hans.lproj/Localizable.strings",
    "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings",
    "Payload/ZFR.app/Arial-BoldMT.strings",
]

print("%-62s | %-30s | %s" % ("IPA", "zh-Hans/Localizable.strings", "Arial-BoldMT.strings"))
print("-" * 130)
for v in VERSIONS:
    p = ROOT / "zombie_farm_ipa" / v
    if not p.exists():
        print("%-62s | (missing)" % v)
        continue
    try:
        z = zipfile.ZipFile(p)
    except Exception as e:  # noqa: BLE001
        print("%-62s | open failed: %s" % (v, e))
        continue
    vals = []
    for t in TABLES:
        try:
            raw = z.read(t)
        except KeyError:
            vals.append("(member absent)")
            continue
        try:
            d = plistlib.loads(raw)
            vals.append(repr(d.get(KEY)) if isinstance(d, dict) else "(not a dict)")
        except Exception:  # noqa: BLE001
            # OpenStep fallback: find the key textually
            txt = raw.decode("utf-8", "replace")
            i = txt.find(KEY)
            vals.append("OpenStep: " + repr(txt[i:i + 70]) if i >= 0 else "(key not found)")
    print("%-62s | %-30s | %s" % (v[:62], vals[0][:30], vals[1]))
    if vals[2] != "(member absent)":
        print("%-62s |   root Arial-BoldMT.strings -> %s" % ("", vals[2]))

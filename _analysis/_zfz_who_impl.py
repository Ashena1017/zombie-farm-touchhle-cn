#!/usr/bin/env python3
"""Which classes implement a given selector (sub9), with imp addresses.

Usage: python _analysis/_zfz_who_impl.py SEL [SEL ...]
"""
from __future__ import annotations

import pathlib as _pl
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import all_methods, classes_by_name  # noqa: E402
import zipfile  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)

want = set(sys.argv[1:])
by = classes_by_name(sl)
for cn, (c, info) in sorted(by.items()):
    for m in all_methods(sl, c, info):
        if m.selector in want:
            print("  %-24s [%-8s] %-40s imp=%#x" % (cn, m.kind, m.selector, m.imp))

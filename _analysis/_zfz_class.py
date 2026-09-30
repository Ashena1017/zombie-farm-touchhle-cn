#!/usr/bin/env python3
"""Resolve a sub9 __objc_classrefs slot (or a raw class object address) to a name.

Usage: python _analysis/_zfz_class.py 0x399fac [more...]
"""
from __future__ import annotations

import pathlib as _pl
import struct
import sys
import zipfile

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import class_ro, classes_by_name, u32  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
by = classes_by_name(sl)
rev = {c: n for n, (c, i) in by.items()}

for a in sys.argv[1:]:
    addr = int(a, 0)
    v = u32(sl, addr)
    print("%#x -> word %s (0x%x)" % (addr, v, v or 0))
    if v and v in rev:
        print("      = class @%s" % rev[v])
    elif v:
        # maybe it's already a class object
        info = class_ro(sl, v)
        if info:
            print("      class_ro name = %s" % info["name"])
        else:
            # deref one more
            v2 = u32(sl, v)
            print("      deref -> %s ; class_ro name = %s" % (
                hex(v2) if v2 else None,
                class_ro(sl, v2)["name"] if v2 and class_ro(sl, v2) else None))

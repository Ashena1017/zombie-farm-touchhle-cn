#!/usr/bin/env python3
"""Dump fertilizer-related keys from the ZFR localization tables + list matching
CFStrings (with addresses) in both slices.

Usage: python _analysis/_zfz_strings.py [ipa] [needle ...]
"""
from __future__ import annotations

import pathlib as _pl
import plistlib
import struct
import sys
import zipfile


def _find_project_root(start):
    for _p in [start, *start.parents]:
        if (_p / "tools" / "audit_zfr_ipa.py").exists():
            return _p
    raise RuntimeError("project root not found above %s" % start)


ROOT = _find_project_root(_pl.Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = sys.argv[1] if len(sys.argv) > 1 else str(
    ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
NEEDLES = sys.argv[2:] or ["Fertiliz", "fertiliz", "\u65bd\u80a5", "\u5316\u80a5"]

z = zipfile.ZipFile(IPA)
names = [n for n in z.namelist() if n.endswith(".strings")]
print("== .strings members ==")
for n in names:
    print("  ", n, z.getinfo(n).file_size)

print("\n== table hits ==")
for n in names:
    try:
        d = plistlib.loads(z.read(n))
    except Exception as e:  # noqa: BLE001
        print(f"  {n}: parse failed: {e}")
        continue
    if not isinstance(d, dict):
        continue
    for k, v in d.items():
        ks = k if isinstance(k, str) else str(k)
        vs = v if isinstance(v, str) else str(v)
        if any(x in ks or x in vs for x in NEEDLES):
            print(f"  {n}\n      key={ks!r} value={vs!r}")

fat = z.read("Payload/ZFR.app/ZFR")
print("\n== CFStrings in the executable ==")
for sl in parse_fat(fat):
    cs = {}
    for sec in sl.sections:
        if sec.name != "__cstring":
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        p = 0
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            try:
                cs[sec.addr + p] = blob[p:e].decode("utf-8")
            except Exception:  # noqa: BLE001
                pass
            p = e + 1
    cf = {}
    for sec in sl.sections:
        if sec.name not in ("__cfstring", "__objc_cfstring"):
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            o = sl.addr_to_file(a)
            if o is None or o + 4 > len(sl.data):
                continue
            v = struct.unpack_from("<I", sl.data, o)[0]
            s = cs.get(v)
            if s:
                cf[a - 8] = s
    for a, s in sorted(cf.items()):
        if any(x in s for x in NEEDLES):
            print(f"   sub{sl.subtype}  CFSTR @{a:#x}: {s!r}")

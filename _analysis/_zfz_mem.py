#!/usr/bin/env python3
"""Read raw u32/f32/f64 at addresses in sub9; also resolve pointer targets.

Usage: python _analysis/_zfz_mem.py 0x3ca08 0x3ca10 ... [--ipa X]
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
from inspect_v3_facts import class_ro, classes_by_name  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
by = classes_by_name(sl)
rev = {c: n for n, (c, i) in by.items()}


def sec(a):
    for s in sl.sections:
        if s.addr <= a < s.addr + s.size:
            return s.name
    return None


def rd(a, n):
    o = sl.addr_to_file(a)
    return None if o is None else sl.data[o:o + n]


for a in pos:
    addr = int(a, 0)
    b8 = rd(addr, 8)
    b4 = rd(addr, 4)
    if b4 is None:
        print("%#x: unmapped" % addr)
        continue
    w = struct.unpack("<I", b4)[0]
    f32 = struct.unpack("<f", b4)[0]
    f64 = struct.unpack("<d", b8)[0] if b8 and len(b8) == 8 else None
    extra = ""
    if w in rev:
        extra = " = class %s" % rev[w]
    elif sec(w) == "__objc_selrefs":
        o = sl.addr_to_file(w)
        p = struct.unpack_from("<I", sl.data, o)[0]
        extra = " -> selref %r" % sl.cstr(p)
    elif sec(w) in ("__cstring", "__objc_methname"):
        extra = " -> %r" % sl.cstr(w)
    elif sec(w) == "__cfstring":
        extra = " -> CFString"
    print("%#010x [%s]  u32=%#010x  f32=%g  f64=%r%s"
          % (addr, sec(addr), w, f32, f64, extra))
    if b8 and len(b8) == 8:
        print("            bytes = %s" % b8.hex())

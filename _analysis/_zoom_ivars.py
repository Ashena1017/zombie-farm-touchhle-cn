# -*- coding: utf-8 -*-
"""Dump ZFFarmTileMap ivars and resolve the ivar-offset slots used by its touch handlers."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, read_ivars  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]
cls = classes_by_name(sl)

by_off = {}
for name in ("ZFFarmTileMap",):
    _c, info = cls[name]
    ivs = read_ivars(sl, info["ivars"])
    print(f"==== {name}: {len(ivs)} ivars ====")
    for iv in ivs:
        by_off[iv["offset"]] = iv
        print(f"   +0x{iv['offset']:03x}  {iv['name']:34s} {iv['type']}")

SLOTS = [
    (0x3baae2, "ccTouchMoved 0x610c/0x6116"),
    (0x3baae8, "ccTouchMoved 0x6124/0x612c"),
    (0x3baaec, "ccTouchMoved 0x613c/0x6144"),
    (0x3baad2, "ccTouchMoved 0x61e6/0x61ee"),
    (0x3baaf0, "ccTouchMoved 0x6208/0x6214"),
]
print("\n==== candidate ivar-offset slots ====")
for slot, where in SLOTS:
    for delta in (-2, 0, 2):
        va = slot + delta
        off = sl.addr_to_file(va)
        if off is None:
            continue
        val = struct.unpack_from("<I", sl.data, off)[0]
        if 0 < val < 0x1000:
            iv = by_off.get(val)
            nm = iv["name"] if iv else "?"
            ty = iv["type"] if iv else ""
            print(f"   0x{va:x}  ({where})  -> +0x{val:x} = {nm}  {ty}")

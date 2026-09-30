# -*- coding: utf-8 -*-
"""Resolve the CCScaleTo-style action used by setZoomOutAmount:, plus the
class refs it uses, and ZFFarmTileMap's superclass."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]
methname = next(s for s in sl.sections if s.name == "__objc_methname")


def rd32(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<I", sl.data, off)[0]


def cstr(va):
    if va is None:
        return None
    off = sl.addr_to_file(va)
    if off is None:
        return f"<0x{va:x} not file-backed>"
    end = sl.data.index(b"\0", off)
    return sl.data[off:end].decode("ascii", "replace")


def sel_at(slot):
    v = rd32(slot)
    return cstr(v) if v is not None else None


print("=== setZoomOutAmount: action factory ===")
print(f"  SEL slot 0x393b0e -> \"{sel_at(0x393b0e)}\"")
print(f"  class ref [0x399e34] = 0x{rd32(0x399e34):x}  name={cstr(rd32(rd32(0x399e34)+16) if rd32(0x399e34) else 0)}")
print(f"  winSize receiver [0x399e30] = 0x{rd32(0x399e30):x}")

print("\n=== what class is at 0x39f404 (action factory receiver)? ===")
cls = classes_by_name(sl)
for name, (addr, info) in sorted(cls.items()):
    if addr == 0x39f404:
        print(f"   {name}  ro=0x{info['ro']:x}")

print("\n=== ZFFarmTileMap hierarchy ===")
c, info = cls["ZFFarmTileMap"]
print(f"   class=0x{c:x} ro=0x{info['ro']:x} name={info['name']}")
# superclass pointer is at class+4 in __objc_data
sup = rd32(c + 4)
for name, (addr, inf) in sorted(cls.items()):
    if addr == sup:
        print(f"   superclass = {name} (0x{sup:x})")
        sup2 = rd32(addr + 4)
        for n2, (a2, i2) in sorted(cls.items()):
            if a2 == sup2:
                print(f"      -> {n2} (0x{sup2:x})")
print(f"   does ZFFarmTileMap respond to 'scale'? (CCNode method)")

print("\n=== every 'scale'-family selector implemented by ZFFarmTileMap chain ===")
for m in sorted(sl.methods, key=lambda x: (x.cls, x.selector)):
    if m.cls in ("ZFFarmTileMap", "CCNode") and m.selector in (
        "scale", "setScale:", "scaleX", "scaleY", "runAction:", "numberOfRunningActions"
    ):
        print(f"   {m.cls:16s} -{m.selector:24s} imp=0x{m.imp:x}")

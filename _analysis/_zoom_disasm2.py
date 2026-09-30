# -*- coding: utf-8 -*-
"""Disassemble ZFFarmTileMap touch handlers (the gesture path)."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]

ranges = {}
for m, s, e in sl.method_ranges():
    ranges[(m.cls, m.selector)] = (m, s, e)

for cls, sel, limit in [
    ("ZFFarmTileMap", "ccTouchBegan:withEvent:", 70),
    ("ZFFarmTileMap", "ccTouchMoved:withEvent:", 90),
    ("ZFFarmTileMap", "ccTouchEnded:withEvent:", 70),
    ("ZFFarmTileMap", "dragFrom:to:", 40),
    ("ZFFarmTileMap", "keepMapInBounds", 40),
]:
    key = (cls, sel)
    if key not in ranges:
        print(f"\n==== {cls} -{sel}: NOT FOUND ====")
        continue
    m, start, end = ranges[key]
    print(f"\n==== {m.cls} -{sel} imp=0x{m.imp:x} ====")
    for line in sl.disasm(start, end, thumb=True)[:limit]:
        print("   " + line)

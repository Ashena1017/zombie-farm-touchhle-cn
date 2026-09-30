# -*- coding: utf-8 -*-
"""Disassemble the zoom-related method implementations."""
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

WANT = [
    ("ZFFarmTileMap", "setZoomOutAmount:"),
    ("ZFTileManager", "resetCamera"),
    ("ZFTileManager", "resetCameraWithZoom:"),
    ("ZFTileManager", "scaleCompensation:"),
    ("ZFFarmTileMap", "initWithGameData:"),
    ("ZFFarmTileMap", "keepMapInBounds"),
    ("ZFFarmTileMap", "tick:"),
]

ranges = {m.selector: (m, s, e) for m, s, e in sl.method_ranges()}

for cls, sel in WANT:
    key = sel
    if key not in ranges:
        print(f"\n==== {cls} {sel}: NOT FOUND ====")
        continue
    m, start, end = ranges[key]
    if m.cls != cls:
        print(f"\n==== {cls} {sel}: owner is {m.cls} ====")
    print(f"\n==== {m.cls} -{sel}  imp=0x{m.imp:x} range=[0x{start:x},0x{end if end is None else hex(end)}) ====")
    for line in sl.disasm(start, end, thumb=True)[:90]:
        print("   " + line)

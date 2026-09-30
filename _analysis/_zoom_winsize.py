# -*- coding: utf-8 -*-
"""Decide which clamp branch -setZoomOutAmount: takes for our launch config,
by finding what CCDirector -winSize returns under --device-family=ipad --scale-hack=1."""
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

print("=== CCDirector -winSize ===")
for m in sl.methods:
    if m.cls == "CCDirector" and m.selector in ("winSize", "winSizeInPixels", "setWinSize:"):
        print(f"   -{m.selector:20s} imp=0x{m.imp:x}")

print("\n=== CCDirector ivars ===")
_c, info = cls["CCDirector"]
for iv in read_ivars(sl, info["ivars"]):
    print(f"   +0x{iv['offset']:03x}  {iv['name']:26s} {iv['type']}")

# Also check touchHLE: what does it report for winSize? (eagl.rs / CCDirector handling)
print("\n=== touchHLE side: where winSize / surface size is produced ===")
rs = ROOT / "touchHLE" / "touchHLE-fork" / "src"
for path in rs.rglob("*.rs"):
    txt = path.read_text(encoding="utf-8", errors="replace")
    if "winSize" in txt:
        for i, line in enumerate(txt.splitlines(), 1):
            if "winSize" in line:
                print(f"   {path.relative_to(ROOT)}:{i}: {line.strip()[:110]}")

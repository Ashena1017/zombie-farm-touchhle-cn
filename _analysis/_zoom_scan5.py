# -*- coding: utf-8 -*-
"""Map zoom/camera/gesture selectors to their owning ObjC classes and disassemble the IMPs."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
EXECUTABLE = "Payload/ZFR.app/ZFR"

with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)

slices = parse_fat(fat)
print("slices:", [(s.subtype, hex(len(s.data))) for s in slices])
sl = [s for s in slices if s.subtype == 9][0]

# index all methods by selector
by_sel = {}
for m in sl.methods:
    by_sel.setdefault(m.selector, []).append(m)

TARGETS = [
    "setZoomOutAmount:", "zoomFactor", "resetCameraWithZoom:", "scaleCompensation:",
    "initElementsWithWindowScale::atX:Y:", "scrollViewDidZoom:", "viewForZoomingInScrollView:",
    "addGestureRecognizer:", "touchesBegan:withEvent:", "ccTouchesBegan:withEvent:",
    "scrollViewWillBeginZooming:withView:", "scrollViewDidEndZooming:withView:atScale:",
    "resetCamera", "zoomScale", "setZoomScale:", "maximumZoomScale", "minimumZoomScale",
]

print("\n================ selector -> owning class ================")
for t in TARGETS:
    ms = by_sel.get(t, [])
    print(f"\n--- {t}  ({len(ms)} impl) ---")
    for m in ms:
        print(f"    {m.cls:34s} kind={m.kind:16s} imp=0x{m.imp:x} types={m.types}")

# classes that implement zoom-related things
print("\n================ classes with zoom-ish selectors ================")
KEY = ("zoom", "Zoom", "Camera", "camera", "Gesture", "gesture", "Scale", "scale")
owner = {}
for m in sl.methods:
    if any(k in m.selector for k in KEY):
        owner.setdefault(m.cls, []).append(m.selector)
for cls in sorted(owner):
    sels = sorted(set(owner[cls]))
    print(f"\n  {cls}  ({len(sels)})")
    for s in sels[:40]:
        print(f"      {s}")

# -*- coding: utf-8 -*-
"""Determine the sign convention of zoomFactor: does a larger value zoom the map IN?

Evidence chain:
  * -setZoomOutAmount: stores its (clamped) argument into the `zoomFactor` ivar.
  * It then runs [CCScaleTo actionWithDuration:scale:] on the tile map itself,
    so zoomFactor IS the node scale: scale > 1 = bigger map = zoomed in.
  * -resetCamera calls setZoomOutAmount: with 1.0, and -resetCameraWithZoom:
    forwards its argument, so the "neutral" level is 1.0.
  * -ccTouchMoved: sets new = (newDistance/initialDistance) * originalScale,
    i.e. spreading the fingers (bigger distance) INCREASES the value.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]
text = next(s for s in sl.sections if s.name == "__text")
ranges = {m.selector: (m, s, e) for m, s, e in sl.method_ranges()}

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

print("=== -resetCamera calls setZoomOutAmount: with what argument? ===")
m, start, end = ranges["resetCamera"]
size = end - start
code = sl.data[text.offset + (start - text.addr): text.offset + (start - text.addr) + size]
for ins in md.disasm(code, start):
    if ins.address >= 0x3aab0:
        print(f"   0x{ins.address:06x}  {ins.mnemonic:<10} {ins.op_str}")

print("\n=== -ccTouchMoved: arithmetic that produces the new zoom ===")
m, start, end = ranges["ccTouchMoved:withEvent:"]
size = end - start
code = sl.data[text.offset + (start - text.addr): text.offset + (start - text.addr) + size]
for ins in md.disasm(code, start):
    if 0x61e6 <= ins.address <= 0x6238:
        print(f"   0x{ins.address:06x}  {ins.mnemonic:<10} {ins.op_str}")

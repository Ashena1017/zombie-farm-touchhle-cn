# -*- coding: utf-8 -*-
"""Final checks: (a) resolve the isMultipleTouchEnabled getter, (b) scan IPA resources for zoom UI."""
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
    names = z.namelist()
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]

# ---- (a) resolve selref slots used near the setMultipleTouchEnabled: call ----
selrefs = next(s for s in sl.sections if s.name == "__objc_selrefs")
methname = next(s for s in sl.sections if s.name == "__objc_methname")

def selref_at(insn_addr, imm):
    """Thumb: ldr rX,[pc,#imm] -> pool slot address."""
    slot = ((insn_addr + 4) & ~3) + imm
    off = sl.addr_to_file(slot)
    if off is None:
        return f"<slot 0x{slot:x} not file-backed>"
    va = struct.unpack_from("<I", sl.data, off)[0]
    return f"0x{va:x} = {sl.cstr(va)}"

print("=== selrefs in CCDirector initOpenGLViewWithView:withFrame: ===")
print("  0x21242c ldr r1,[pc,#?] (getter)   ->", selref_at(0x212428, 0x5e28))
print("  0x21244a ldr r1,[pc,#?] (setter)   ->", selref_at(0x212448, 0x4258))

# also the app delegate sites
print("  0x125efa area getter               ->", selref_at(0x125ef6, 0xf8a6))
print("  0x125f0a area setter               ->", selref_at(0x125f08, 0x798))

# ---- (b) scan IPA resources for zoom-ish names ----
print("\n=== IPA entries whose path mentions zoom/pinch/magnify ===")
hits = [n for n in names if re.search(r"zoom|pinch|magnif", n, re.I)]
for n in hits:
    print("   ", n)
print(f"   ({len(hits)} path hit(s))")

print("\n=== text-ish IPA entries containing 'zoom' ===")
total = 0
for n in names:
    if n.endswith("/"):
        continue
    low = n.lower()
    if not low.endswith((".plist", ".json", ".txt", ".xml", ".strings", ".frag", ".vert", ".lua", ".csv", ".ini", ".cfg")):
        continue
    try:
        with zipfile.ZipFile(IPA) as z:
            raw = z.read(n)
    except Exception:
        continue
    for m in re.finditer(rb"[\x20-\x7e]{3,}", raw):
        s = m.group().decode("ascii")
        if re.search(r"zoom|pinch|magnif", s, re.I):
            print(f"   {n}: {s[:100]}")
            total += 1
            if total > 60:
                break
    if total > 60:
        break
print(f"   ({total} content hit(s))")

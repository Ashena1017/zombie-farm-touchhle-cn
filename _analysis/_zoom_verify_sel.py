# -*- coding: utf-8 -*-
"""Verify (a) the CCScaleTo selector used by setZoomOutAmount:, (b) how zoomFactor
(+0xd4) and the node scale are initialised, (c) which clamp branch our device hits."""
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
methname = next(s for s in sl.sections if s.name == "__objc_methname")
cls = classes_by_name(sl)
_c, info = cls["ZFFarmTileMap"]
ivs = {iv["offset"]: iv["name"] for iv in read_ivars(sl, info["ivars"])}


def rd32(va):
    off = sl.addr_to_file(va)
    return None if off is None else struct.unpack_from("<I", sl.data, off)[0]


def cstr(va):
    off = sl.addr_to_file(va)
    if off is None:
        return "<not file-backed>"
    end = sl.data.index(b"\0", off)
    return sl.data[off:end].decode("ascii", "replace")


print("=== (a) selectors referenced in setZoomOutAmount: ===")
# 0x7f0a -> selref slot via add r0,pc ; ldr r1,[r0]
for insn, imm, label in ((0x7ef2, 0xbc26, "CCScaleTo factory"), (0x7f0a, 0xbc08, "runAction:")):
    slot = ((insn + 4) & ~3) + imm
    selva = rd32(slot)
    print(f"   {label:20s} slot=0x{slot:x} -> SEL 0x{selva:x} = \"{cstr(selva)}\"")

print("\n=== (b) stores to zoomFactor (+0xd4) / originalScale (+0xe4) across the binary ===")
# Find `str`/`vstr` sites whose base register resolves to obj+0xd4 is hard statically;
# instead look for the ivar-offset slot constant 0xd4 / 0xe4 inside __text literal pools.
text = next(s for s in sl.sections if s.name == "__text")
code = sl.data[text.offset:text.offset + text.size]
for off_val, nm in ((0xD4, "zoomFactor"), (0xE4, "originalScale"), (0xD0, "initialDistance")):
    needle = struct.pack("<I", off_val)
    sites = []
    start = 0
    while True:
        p = code.find(needle, start)
        if p < 0:
            break
        start = p + 1
        if p % 4 == 0:
            sites.append(text.addr + p)
    print(f"   +0x{off_val:x} {nm:16s}: {len(sites)} literal(s) -> {[hex(x) for x in sites[:8]]}")

print("\n=== (c) ZFFarmTileMap methods that could set the initial scale ===")
for m in sorted(sl.methods, key=lambda x: x.selector):
    if m.cls == "ZFFarmTileMap":
        print(f"   {m.selector:46s} 0x{m.imp:x}")

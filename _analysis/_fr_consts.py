#!/usr/bin/env python3
"""Dump the double/float constants that feed setAnimationInterval: and friends."""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"

# (addr, note) — sub6 (ARM slice)
SITES6 = [
    (0x0D3EE0, "double const near anim-interval #1"),
    (0x190BD8, "double loaded by AppDelegate applicationDidFinishLaunching:+0x384"),
    (0x2A16D0, "double const #3"),
    (0x2A2D30, "double const #4"),
    (0x2C7CD0, "double 0.25 in CCDirector pause"),
]
# sub9 (Thumb slice)
SITES9 = [
    (0x09B380, "double const sub9 #1"),
    (0x1262B8, "double const sub9 #2"),
    (0x09B378, "float 1/30? sub9"),
]


def show(sl, addr, note):
    off = sl.addr_to_file(addr)
    if off is None:
        print(f"  sub{sl.subtype} {addr:#x}: <not mapped>")
        return
    b = sl.data[off:off + 8]
    d = struct.unpack("<d", b)[0]
    lo = struct.unpack("<f", b[:4])[0]
    hi = struct.unpack("<f", b[4:])[0]
    print(
        f"  sub{sl.subtype} {addr:#010x}: {b.hex()}  "
        f"f64={d!r}  f32lo={lo!r}  f32hi={hi!r}   {note}"
    )


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    slices = {sl.subtype: sl for sl in parse_fat(fat)}
    print(f"=== {IPA} ===")
    print("-- sub6 (ARM) --")
    for a, n in SITES6:
        show(slices[6], a, n)
    print("-- sub9 (Thumb) --")
    for a, n in SITES9:
        show(slices[9], a, n)

    # Also: scan __text for every literal word that decodes to exactly 1/60 or 1/30
    print("\n-- all 1/60 and 1/30 doubles in sub6 __text literal pools --")
    sl = slices[6]
    txt = next(s for s in sl.sections if s.name == "__text")
    target60 = struct.pack("<d", 1.0 / 60.0)
    target30 = struct.pack("<d", 1.0 / 30.0)
    for pat, label in ((target60, "1/60"), (target30, "1/30")):
        hits = []
        start = 0
        blob = sl.data[txt.offset:txt.offset + txt.size]
        while True:
            i = blob.find(pat, start)
            if i < 0:
                break
            hits.append(txt.addr + i)
            start = i + 1
        print(f"  {label}: {[hex(h) for h in hits]}")


if __name__ == "__main__":
    main()

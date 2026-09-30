#!/usr/bin/env python3
"""v18fix - two more font sites that the v3/v5/v6 sweep missed, both because the
class/factory rebuilt its own label instead of using the inherited one.

    #2  the storage item detail panel  (ZFAlertWindowStorageItem)
        title 20.0 -> 24.0

    #6  the shop purchase confirmation  (ZFMarketMenu -checkBoughtItem:)
        body 14.0 -> 18.0

WHY THESE WERE MISSED
---------------------
v3 pinned the base class `ZFAlertWindow -initWithWindow:`, v5 covered the 14
`ZFAlertWindow*` subclasses, and v6 covered `ZFMarketMenu -unlockItem:`.  Both
defects here are *different* code in classes that already looked handled:

*  `ZFAlertWindowStorageItem` overrides the whole slide-in factory, so the base
   class site never runs for it.  The same shape bit `ZFAlertWindowFlurryOffer`
   in v5 (README 7.6).

*  `-[ZFMarketMenu checkBoughtItem:]` builds its confirmation label with the
   "factory rebuild" idiom -- a fresh
   `labelWithString:dimensions:alignment:fontName:fontSize:` call whose
   `fontSize` goes to `[sp,#0xc]` -- exactly like `-unlockItem:` that v6 fixed.
   The instruction bytes are in fact IDENTICAL to v6's site:

       v6  sub6 0x6A49C  mov r2,#0x1600000   '1626a0e3' -> '1926a0e3'
       v18 sub6 0x6B7C8  mov r2,#0x1600000   '1626a0e3' -> '1926a0e3'
       v6  sub9 0x4D6F4  movt r3,#0x4160     'c4f26013' -> 'c4f29013'
       v18 sub9 0x4E5FA  movt r3,#0x4160     'c4f26013' -> 'c4f29013'

THE TIERS
---------
The game builds font sizes as IEEE-754 floats:

    ARM   `mov rX,#0x1a00000` + `orr rX,rX,#0x40000000`   -> 0x41a00000 = 20.0
    Thumb `movs rX,#0` + `movt rX,#0x41a0`                 -> 20.0

and v5's entire title/body sweep was `20.0 -> 24.0` / `14.0 -> 18.0`.  So a lone
`20.0` inside an alert-window factory is that window's title size, and every
`14.0` inside a `labelWithString:...fontSize:` rebuild is a body size.
`ZFAlertWindowStorageItem` has exactly one 20.0 and one 18.0 in each slice, which
is what makes this a confident read rather than a guess.

All four edits are single width-preserving immediates, decoded back to a float
before and after.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_zfr_alert_fonts import (  # noqa: E402
    EXECUTABLE, fat_descriptors, outside_ranges_equal, replace_zip_member,
    sha256, write_exclusive,
)

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed-fonts-v17fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v18fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v18fix.report.json"

# (subtype, addr, expected old bytes, new bytes, note)
SITES: list[tuple[int, int, str, str, str]] = [
    (6, 0x1AAE94, "1a36a0e3", "1c36a0e3",
     "#2 ZFAlertWindowStorageItem title 20.0 -> 24.0 (mov r3,#0x1a00000 -> #0x1c00000)"),
    (9, 0x139D16, "c4f2a012", "c4f2c012",
     "#2 ZFAlertWindowStorageItem title 20.0 -> 24.0 (movt r2,#0x41a0 -> #0x41c0)"),
    (6, 0x6B7C8, "1626a0e3", "1926a0e3",
     "#6 ZFMarketMenu -checkBoughtItem: body 14.0 -> 18.0 (mov r2,#0x1600000 -> #0x1900000)"),
    (9, 0x4E5FA, "c4f26013", "c4f29013",
     "#6 ZFMarketMenu -checkBoughtItem: body 14.0 -> 18.0 (movt r3,#0x4160 -> #0x4190)"),
]

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5)],
}

# what each replacement must decode to, so a typo cannot slip through
EXPECT = {
    ("arm", 0x1C00000): 24.0, ("arm", 0x1900000): 18.0,
    ("thumb", 0x41C0): 24.0, ("thumb", 0x4190): 18.0,
}


def decode_arm_mov_imm(raw: bytes) -> int:
    w = struct.unpack_from("<I", raw, 0)[0]
    if (w & 0x0FE00000) != 0x03A00000:
        raise ValueError("not an ARM mov-immediate: %s" % raw.hex())
    rot = ((w >> 8) & 0xF) * 2
    imm8 = w & 0xFF
    return ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8


def decode_thumb_movt(raw: bytes) -> int:
    f, s2 = struct.unpack_from("<HH", raw, 0)
    if (f & 0xFBF0) != 0xF2C0 or (s2 & 0x8000) != 0:
        raise ValueError("not a Thumb movt: %s" % raw.hex())
    return (((f & 0xF) << 12) | (((f >> 10) & 1) << 11)
            | (((s2 >> 12) & 7) << 8) | (s2 & 0xFF))


def as_float(subtype: int, raw: bytes) -> float:
    if subtype == 6:
        val = decode_arm_mov_imm(raw)
        return struct.unpack("<f", struct.pack("<I", val | 0x40000000))[0]
    imm16 = decode_thumb_movt(raw)
    return struct.unpack("<f", struct.pack("<I", imm16 << 16))[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    ap.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    ap.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from audit_zfr_ipa import parse_fat

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        original = archive.read(EXECUTABLE)

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != {6, 9}:
        raise ValueError("unexpected FAT slice set")

    out = bytearray(original)
    applied: list[dict[str, Any]] = []

    for subtype, addr, old_hex, new_hex, note in SITES:
        old, new = bytes.fromhex(old_hex), bytes.fromhex(new_hex)
        if len(old) != len(new):
            raise ValueError("width change at %#x" % addr)
        for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
            if addr < hi and lo < addr + len(new):
                raise ValueError("sub%d %#x overlaps forbidden %#x" % (subtype, addr, lo))
        before = as_float(subtype, old)
        after = as_float(subtype, new)
        want_after = EXPECT[("arm" if subtype == 6 else "thumb",
                             decode_arm_mov_imm(new) if subtype == 6
                             else decode_thumb_movt(new))]
        if abs(after - want_after) > 1e-6:
            raise ValueError("sub%d %#x replacement is %g, not %g"
                             % (subtype, addr, after, want_after))
        absolute = descriptors[subtype]["offset"] + slices[subtype].addr_to_file(addr)
        found = bytes(out[absolute:absolute + len(old)])
        if found != old:
            raise ValueError("sub%d %#x: expected %s, found %s"
                             % (subtype, addr, old.hex(), found.hex()))
        out[absolute:absolute + len(new)] = new
        applied.append({"subtype": subtype, "addr": f"{addr:#08x}",
                        "file_offset": absolute, "len": len(new),
                        "old_prefix": old.hex(), "new_prefix": new.hex(),
                        "float_before": before, "float_after": after,
                        "note": note})

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)
    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("executable differs outside the intended ranges")

    final = {s.subtype: s for s in parse_fat(patched)}
    for subtype, addr, _o, _n, _note in SITES:
        sl = final[subtype]
        f = sl.addr_to_file(addr)
        got = as_float(subtype, sl.data[f:f + 4])
        if got not in (18.0, 24.0):
            raise ValueError("readback of sub%d %#x is %g" % (subtype, addr, got))

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "findings": {
            "tiers": "the game builds font sizes as floats; v5's whole sweep was "
                     "20.0 -> 24.0 (titles) and 14.0 -> 18.0 (bodies)",
            "issue_2": "ZFAlertWindowStorageItem overrides the slide-in factory, so the "
                       "base-class title site never runs for it; its only 20.0 is the "
                       "title size -> 24.0",
            "issue_6": "ZFMarketMenu -checkBoughtItem: rebuilds its confirmation label "
                       "with labelWithString:...fontSize: at 14.0, the same idiom v6 "
                       "fixed in -unlockItem: -- the instruction bytes are identical",
        },
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "sites": applied,
        "site_count": len(applied),
        "forbidden_regions": {str(k): [[f"{lo:#x}", f"{hi:#x}"] for lo, hi in v]
                              for k, v in FORBIDDEN_PRIOR.items()},
    }

    if args.dry_run:
        report["dry_run"] = True
        print(json.dumps(report, indent=2))
        return 0

    output, zip_meta = replace_zip_member(source, patched)
    if len(output) != len(source):
        raise ValueError("output archive changed size")
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        if archive.read(EXECUTABLE) != patched:
            raise ValueError("round-trip of the patched member failed")
        if archive.testzip() is not None:
            raise ValueError("output archive failed testzip()")
    write_exclusive(args.output, output)
    report["zip"] = zip_meta
    report["output"] = {"name": args.output.name, "size": len(output),
                        "sha256": sha256(output), "executable_sha256": sha256(patched)}
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("wrote %s  (%d bytes)" % (args.output.name, len(output)))
    print("  ipa sha256 = %s" % report["output"]["sha256"])
    for s in applied:
        print("  sub%d %s  %g -> %g  %s"
              % (s["subtype"], s["addr"], s["float_before"], s["float_after"], s["note"]))
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

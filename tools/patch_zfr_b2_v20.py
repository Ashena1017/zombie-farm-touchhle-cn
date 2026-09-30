#!/usr/bin/env python3
"""v20fix - #4 the tool-bar label's right paren is clipped by the hourglass icon.

ROOT CAUSE (see process.md #4 section for the full chain)
---------------------------------------------------------
The red-box text `瞬間成熟 (10)` is NOT an alert-window label.  It is the
`ZFToolsLayer` ivar `toolName` (CCLabel, +0xd4) plus its shadow (+0xd8), both
created in `ZFToolsLayer -init` as

    labelWithString:'Multi Tool' fontName:'AmericanTypewriter-Bold' fontSize:20.0

and right-anchored (`setAnchorPoint:(1.0, 0.5)`), so the label's RIGHT edge is
pinned at  `x = winWidth/2 - 56` (toolName) and `winWidth/2 - 54` (shadow).
The hourglass/leaf icons of the active-tool button sit at the same right
edge, so the widest string -- `瞬间成熟 (10)` with its two CJK digits -- runs
under the icon.  Narrower counts (`(9)`, `(8)` ...) clear it, which is exactly
what the user observes.

FIX
---
Move both labels 4 px left (one single-bit change per float constant):

    toolName       x: -56.0 -> -60.0
    toolNameShadow x: -54.0 -> -58.0

The constants live in the `__text` literal pool and each has exactly ONE
`vldr` reader, so the edit cannot affect anything else:

    sub6  pool 0x130c98  0xC2600000 (-56) -> 0xC2700000 (-60)
          pool 0x130c9c  0xC2580000 (-54) -> 0xC2680000 (-58)
    sub9  pool 0xdfac0   0xC2600000 (-56) -> 0xC2700000 (-60)
          pool 0xdfac4   0xC2580000 (-54) -> 0xC2680000 (-58)

Each replacement is a width-preserving 4-byte pool edit; the verifier
checks the decoded floats, not the bit count.)
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
INPUT_NAME = f"{BASE}.fixed-fonts-v19fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v20fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v20fix.report.json"

# (subtype, pool addr, old float bytes LE, new float bytes LE, note)
SITES: list[tuple[int, int, str, str, str]] = [
    (6, 0x130C98, "000060c2", "000070c2",
     "#4 toolName x -56.0 -> -60.0 (vldr @0x130dc0)"),
    (6, 0x130C9C, "000058c2", "000068c2",
     "#4 toolNameShadow x -54.0 -> -58.0 (vldr @0x130ec8)"),
    (9, 0xDFAC0, "000060c2", "000070c2",
     "#4 toolName x -56.0 -> -60.0 (vldr @0xdfbc8)"),
    (9, 0xDFAC4, "000058c2", "000068c2",
     "#4 toolNameShadow x -54.0 -> -58.0 (vldr @0xdfcce)"),
]

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5)],
}

EXPECT = {-56.0: -60.0, -54.0: -58.0}


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
        before = struct.unpack("<f", old)[0]
        after = struct.unpack("<f", new)[0]
        if abs(EXPECT.get(before, 9999) - after) > 1e-6:
            raise ValueError("sub%d %#x: %g -> %g is not the intended move"
                             % (subtype, addr, before, after))
        for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
            if addr < hi and lo < addr + len(new):
                raise ValueError("sub%d %#x overlaps forbidden %#x" % (subtype, addr, lo))
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

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "findings": {
            "root_cause": "ZFToolsLayer toolName/toolNameShadow are right-anchored "
                          "(anchor 1.0,0.5) with right edges at winWidth/2-56 and "
                          "winWidth/2-54; the widest count string '(10)' runs under "
                          "the hourglass icon",
            "fix": "move both right edges 4px left: -56 -> -60, -54 -> -58; each "
                   "pool constant has exactly one vldr reader",
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

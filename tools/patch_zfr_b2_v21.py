#!/usr/bin/env python3
"""v21fix - batch-2 items #2 (storage item panel title/description) and
#8 (Mausoleum button caption +3).

#2  `ZFAlertWindowStorageItem` does not build its own title/description: it
    calls the base factory

        +[ZFAlertWindow alertWindowSlideInInformative:withMessage:withSprite:
          withHudFile:withButtonRect:withButtonSelectedRect:withButtonText:
          withButtonColor:slideFromLeft:]

    which creates `title1` (18.0, black) and `body1` (12.0).  The only two
    callers of that base factory in the whole binary are the storage-item
    subclass itself (0x139bd4) and `-[ZFGuiLayer displayAlertSlideInInformative:...]`
    (0x18d62) -- i.e. the storage item panel and its 9-argument wrapper.  v18
    instead edited `makeWindow:...`'s layout argument (20.0) in the subclass,
    which is why nothing changed on screen.  Fix: 18.0 -> 24.0 (title) and
    12.0 -> 18.0 (body), matching the batch-1 rule title 24 / body 18.

#8  `ZFZombieMenu -initLowerMenu` localises the CFString 'Mausoleum' and builds
    the button caption with `labelWithString:fontName:'AmericanTypewriter-Bold'
    fontSize:14.0` (stored into ivar `lowerMenuLabel1`, +0x124; the label is
    then tinted black by the following `setColor:(0,0,0)`).  Fix: 14.0 -> 17.0.

ENCODINGS
---------
sub9 (Thumb-2) builds the float with `movs rd,#0` + `movt rd,#0x41xx`, so only
the imm8 of the `movt` changes:

    movt rd, #0x4190 -> #0x41c0   (18.0 -> 24.0)
    movt rd, #0x4140 -> #0x4190   (12.0 -> 18.0)
    movt rd, #0x4160 -> #0x4188   (14.0 -> 17.0)

sub6 (ARM) builds it as `mov rd,#lo` + `orr rd,rd,#0x40000000`, so the rotated
8-bit immediate of the MOV changes (the assembler picks the rotation; the
patcher encodes it and decodes it back with capstone to prove the value).
Each site is 4 bytes and the archive size is unchanged.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v20fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v21fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v21fix.report.json"

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5)],
}

# (subtype, addr, style, register, float_before, float_after, note)
#   style 'thumb-movt' : `movt rD, #hi16`, low half already zeroed by `movs`
#   style 'arm-mov'    : `mov rD, #rotated imm`, followed by `orr rD,rD,#0x40000000`
SITES: list[tuple[int, int, str, int, float, float, str]] = [
    (9, 0x076B7A, "thumb-movt", 3, 18.0, 24.0,
     "#2 ZFAlertWindow -alertWindowSlideInInformative: title1 fontSize 18.0 -> 24.0"),
    (9, 0x076DE8, "thumb-movt", 0, 12.0, 18.0,
     "#2 ZFAlertWindow -alertWindowSlideInInformative: body1 fontSize 12.0 -> 18.0"),
    (9, 0x0D290A, "thumb-movt", 0, 14.0, 17.0,
     "#8 ZFZombieMenu -initLowerMenu Mausoleum caption 14.0 -> 17.0"),
    (6, 0x0A31A4, "arm-mov", 3, 18.0, 24.0,
     "#2 ZFAlertWindow -alertWindowSlideInInformative: title1 fontSize 18.0 -> 24.0"),
    (6, 0x0A3464, "arm-mov", 3, 12.0, 18.0,
     "#2 ZFAlertWindow -alertWindowSlideInInformative: body1 fontSize 12.0 -> 18.0"),
    (6, 0x11EFC4, "arm-mov", 3, 14.0, 17.0,
     "#8 ZFZombieMenu -initLowerMenu Mausoleum caption 14.0 -> 17.0"),
]


def thumb_movt(rd: int, imm16: int) -> bytes:
    """MOVT (T1): 11110 i 10 1100 imm4 | 0 imm3 Rd imm8."""
    imm4 = (imm16 >> 12) & 0xF
    i = (imm16 >> 11) & 1
    imm3 = (imm16 >> 8) & 0x7
    imm8 = imm16 & 0xFF
    hw1 = 0xF2C0 | (i << 10) | imm4
    hw2 = (imm3 << 12) | (rd << 8) | imm8
    return struct.pack("<HH", hw1, hw2)


def _ror32(v: int, n: int) -> int:
    n &= 31
    return ((v >> n) | (v << (32 - n))) & 0xFFFFFFFF if n else v & 0xFFFFFFFF


def _rol32(v: int, n: int) -> int:
    n &= 31
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF if n else v & 0xFFFFFFFF


def arm_mov_imm(rd: int, value: int) -> bytes:
    """MOV (A1) with an 8-bit rotated immediate: value == imm8 ROR (2*rot)."""
    for rot in range(16):
        imm8 = _rol32(value, 2 * rot)
        if imm8 <= 0xFF and _ror32(imm8, 2 * rot) == value:
            return struct.pack("<I", 0xE3A00000 | (rd << 12) | (rot << 8) | imm8)
    raise ValueError("%#x cannot be encoded as an ARM rotated immediate" % value)


def encode(style: str, rd: int, f: float) -> bytes:
    bits = struct.unpack("<I", struct.pack("<f", f))[0]
    if bits >> 30 != 1:
        raise ValueError("%g is not a 0x4xxxxxxx float" % f)
    if style == "thumb-movt":
        if bits & 0xFFFF:
            raise ValueError("%g has a non-zero low half" % f)
        return thumb_movt(rd, (bits >> 16) & 0xFFFF)
    if style == "arm-mov":
        # `mov rd,#lo` then `orr rd,rd,#0x40000000`
        return arm_mov_imm(rd, bits & 0x3FFFFFFF)
    raise ValueError("unknown style %r" % style)


def decode(style: str, code: bytes, addr: int, rd: int) -> float:
    """Decode the patched instruction back to the float it materialises."""
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if style == "thumb-movt" else CS_MODE_ARM)
    md.detail = True
    ins = list(md.disasm(code, addr))
    if len(ins) != 1:
        raise ValueError("%#x did not decode as one instruction" % addr)
    imm = ins[0].operands[-1].imm
    if style == "thumb-movt":
        bits = (imm & 0xFFFF) << 16
    else:
        bits = (imm | 0x40000000) & 0xFFFFFFFF
    return struct.unpack("<f", struct.pack("<I", bits))[0]


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

    for subtype, addr, style, rd, before, after, note in SITES:
        old = encode(style, rd, before)
        new = encode(style, rd, after)
        if len(old) != len(new) != 4:
            raise ValueError("sub%d %#x: not width preserving" % (subtype, addr))
        for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
            if addr < hi and lo < addr + len(new):
                raise ValueError("sub%d %#x overlaps forbidden %#x" % (subtype, addr, lo))

        # the patched instruction must decode back to the float we want
        got_new = decode(style, new, addr, rd)
        got_old = decode(style, old, addr, rd)
        if abs(got_new - after) > 1e-6 or abs(got_old - before) > 1e-6:
            raise ValueError("sub%d %#x: encoder round-trip %g / %g"
                             % (subtype, addr, got_old, got_new))

        absolute = descriptors[subtype]["offset"] + slices[subtype].addr_to_file(addr)
        found = bytes(out[absolute:absolute + 4])
        if found != old:
            raise ValueError("sub%d %#x: expected %s, found %s"
                             % (subtype, addr, old.hex(), found.hex()))
        # the reader must still see the register we expect
        raw_new = decode(style, new, addr, rd)
        out[absolute:absolute + 4] = new
        applied.append({"subtype": subtype, "addr": f"{addr:#08x}",
                        "file_offset": absolute, "len": 4,
                        "old_prefix": old.hex(), "new_prefix": new.hex(),
                        "float_before": before, "float_after": raw_new,
                        "style": style, "note": note})

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
            "#2": "ZFAlertWindowStorageItem renders the base factory's title1 (18.0) "
                  "and body1 (12.0); the base slide-in factory has only two callers, "
                  "both on the storage-item path, so raising them to 24/18 only "
                  "affects that panel",
            "#8": "ZFZombieMenu -initLowerMenu builds the Mausoleum caption "
                  "(lowerMenuLabel1, ivar +0x124) at 14.0 and then tints it black; "
                  "raise to 17.0",
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

#!/usr/bin/env python3
"""v23fix - follow-ups reported by the user after testing v22fix.

1) #2  the storage-item panel title is now 24pt but its label is built with a
       fixed `dimensions` box of 200 x 20, so the glyph bottoms are clipped:

           sub9 0x76b9e
             stm.w sp, {r5, fp}   ; [sp] = 20.0 (height), [sp+4] = 1 (alignment)
             ...
             blx objc_msgSend     ; labelWithString:dimensions:alignment:fontName:fontSize:

       `r5` is 0x41a00000 = 20.0 (set once at 0x76aaa) and is shared with
       `makeWindow:...`'s first argument, so the constant cannot simply be
       changed.  Instead the factory call is retargeted to a stub that rewrites
       the *stack* height and tail-calls objc_msgSend:

           movw  r12, #0x0000
           movt  r12, #0x4208        ; 34.0
           str.w r12, [sp]           ; dimensions.height 20.0 -> 34.0
           movw  r12, #0x014c
           movt  r12, #0x002d        ; objc_msgSend (ARM)
           bx    r12                 ; tail call: lr untouched, so objc_msgSend
                                     ; returns straight to the caller

       The text in a cocos2d `labelWithString:dimensions:...` label is drawn
       top-aligned inside the box, which is why the *bottom* was cut while the
       top looked fine -- so a taller box keeps the bottom edge where the cut
       used to be and lets the glyphs grow upwards.

2) #7  the 能力 tab was still white: `-initRightMenu` explicitly colours
       `abilityTabLabel` (ivar +0x12c) white right after creating it:

           sub9 0xcfb1a  ldr.w r0, [sl, r8]    ; r8 = 0x12c
           sub9 0xcfb1e  mvn   r2, #0xff000000 ; r2 = 0x00FFFFFF = white
           sub9 0xcfb24  blx   objc_msgSend    ; [abilityTabLabel setColor:white]

       The 数值 label has no such call (which is why v22 fixed it).  Replace the
       `mvn` with `mov.w r2, #0`.

3) #8  the Mausoleum caption is still a bit small: 17.0 -> 19.0.

sub6 is untouched this round (the two stub-based fixes are sub9-only; see
process.md for why).
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
INPUT_NAME = f"{BASE}.fixed-fonts-v22fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v23fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v23fix.report.json"

EXEC_MSGSEND = 0x2D014C
STUB2 = 0x1138F4                 # right after the v22 stub + literal
STUB2_LEN = 22
TITLE_H_BEFORE = 20.0
TITLE_H_AFTER = 34.0

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5), (0x1138C8, 0x1138F3)],
}


# ---------------------------------------------------------------- encoders
def thumb_movw(rd: int, imm16: int) -> bytes:
    imm4 = (imm16 >> 12) & 0xF
    i = (imm16 >> 11) & 1
    imm3 = (imm16 >> 8) & 0x7
    imm8 = imm16 & 0xFF
    return struct.pack("<HH", 0xF240 | (i << 10) | imm4,
                       (imm3 << 12) | (rd << 8) | imm8)


def thumb_movt(rd: int, imm16: int) -> bytes:
    imm4 = (imm16 >> 12) & 0xF
    i = (imm16 >> 11) & 1
    imm3 = (imm16 >> 8) & 0x7
    imm8 = imm16 & 0xFF
    return struct.pack("<HH", 0xF2C0 | (i << 10) | imm4,
                       (imm3 << 12) | (rd << 8) | imm8)


def thumb_bl(addr: int, target: int, link: bool = True) -> bytes:
    base = (addr + 4) if link else ((addr + 4) & ~3)
    off = target - base
    if off % 2 or off < -0x1000000 or off > 0xFFFFFF:
        raise ValueError("branch offset %#x out of range" % off)
    S = (off >> 24) & 1
    I1 = (off >> 23) & 1
    I2 = (off >> 22) & 1
    hw1 = 0xF000 | (S << 10) | ((off >> 12) & 0x3FF)
    hw2 = (0xD000 if link else 0xC000) \
        | ((1 - (I1 ^ S)) << 13) | ((1 - (I2 ^ S)) << 11) | ((off >> 1) & 0x7FF)
    code = struct.pack("<HH", hw1, hw2)
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    ins = list(md.disasm(code, addr))
    if len(ins) != 1 or ins[0].mnemonic != ("bl" if link else "blx") \
            or (ins[0].operands[0].imm & ~1) != (target & ~1):
        raise ValueError("branch round-trip failed at %#x -> %#x" % (addr, target))
    return code


def build_stub2(addr: int) -> bytes:
    bits = struct.unpack("<I", struct.pack("<f", TITLE_H_AFTER))[0]
    if bits >> 30 != 1 or bits & 0xFFFF:
        raise ValueError("height %g is not a 0x42xxxxxx float" % TITLE_H_AFTER)
    hi = (bits >> 16) & 0xFFFF
    code = b"".join([
        thumb_movw(12, 0),                      # movw r12, #0
        thumb_movt(12, hi),                     # movt r12, #0x4208  (34.0)
        struct.pack("<HH", 0xF8CD, 0xC000),     # str.w r12, [sp]
        thumb_movw(12, EXEC_MSGSEND & 0xFFFF),  # movw r12, #0x014c
        thumb_movt(12, EXEC_MSGSEND >> 16),     # movt r12, #0x002d
        struct.pack("<H", 0x4760),              # bx   r12  (BX T1, bits 6..3 = Rm)
    ])
    if len(code) != STUB2_LEN:
        raise ValueError("stub2 is %d bytes, expected %d" % (len(code), STUB2_LEN))
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(code, addr)]
    want = ["movw ip, #0", "movt ip, #0x4208", "str.w ip, [sp]",
            "movw ip, #0x14c", "movt ip, #0x2d", "bx ip"]
    if got != want:
        raise ValueError("stub2 assembly mismatch:\n  got  %s\n  want %s" % (got, want))
    return code


# ------------------------------------------------------------------- main
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

    stub2 = build_stub2(STUB2)
    for lo, hi in FORBIDDEN_PRIOR[9]:
        if STUB2 < hi and lo < STUB2 + STUB2_LEN:
            raise ValueError("stub2 %#x overlaps forbidden %#x" % (STUB2, lo))

    out = bytearray(original)
    applied: list[dict[str, Any]] = []

    def apply(subtype, addr, old_hex, new, note, kind="site"):
        old = bytes.fromhex(old_hex)
        absolute = descriptors[subtype]["offset"] + slices[subtype].addr_to_file(addr)
        found = bytes(out[absolute:absolute + len(old)])
        if found != old:
            raise ValueError("sub%d %#x: expected %s, found %s"
                             % (subtype, addr, old_hex, found.hex()))
        if len(new) != len(old):
            raise ValueError("sub%d %#x: not width preserving" % (subtype, addr))
        out[absolute:absolute + len(new)] = new
        applied.append({"subtype": subtype, "addr": f"{addr:#08x}",
                        "file_offset": absolute, "len": len(new), "kind": kind,
                        "old_prefix": old.hex(), "new_prefix": new.hex(), "note": note})

    # 1. the title-dimensions stub
    apply(9, STUB2, bytes(slices[9].data[slices[9].addr_to_file(STUB2):
                                      slices[9].addr_to_file(STUB2) + STUB2_LEN]).hex(),
          stub2, "#2 dimensions.height 20.0 -> 34.0 wrapper stub", kind="stub")
    apply(9, 0x76B9E, "59f2d6ea", thumb_bl(0x76B9E, STUB2, link=True),
          "#2 title1 label factory -> height-fix stub")

    # 2. the 能力 tab's explicit white
    apply(9, 0xCFB1E, "6ff07f42", bytes.fromhex("4ff00002"),
          "#7 abilityTabLabel setColor:(0,0,0) instead of white")

    # 3. Mausoleum caption 17.0 -> 19.0
    def thumb_movt_for(rd, f):
        bits = struct.unpack("<I", struct.pack("<f", f))[0]
        return thumb_movt(rd, (bits >> 16) & 0xFFFF)

    def arm_mov_imm(rd, value):
        for rot in range(16):
            n = 2 * rot
            imm8 = ((value << n) | (value >> (32 - n))) & 0xFFFFFFFF if n else value
            if imm8 <= 0xFF and ((imm8 >> n) | (imm8 << (32 - n))) & 0xFFFFFFFF == value:
                return struct.pack("<I", 0xE3A00000 | (rd << 12) | (rot << 8) | imm8)
        raise ValueError("%#x not encodable as an ARM rotated immediate" % value)

    bits19 = struct.unpack("<I", struct.pack("<f", 19.0))[0]
    apply(9, 0xD290A, "c4f28810", thumb_movt_for(0, 19.0),
          "#8 Mausoleum caption 17.0 -> 19.0")
    apply(6, 0x11EFC4, "6237a0e3", arm_mov_imm(3, bits19 & 0x3FFFFFFF),
          "#8 Mausoleum caption 17.0 -> 19.0")

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
        "#1": "title1's dimensions box (200x20) clipped the 24pt glyph bottoms; "
              "a stub rewrites the stack height to 34.0 and tail-calls objc_msgSend",
        "#7": "abilityTabLabel was explicitly set white at 0xcfb1e; now 0",
        "#8": "Mausoleum caption 17.0 -> 19.0",
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "stub": {"addr": f"{STUB2:#x}", "len": STUB2_LEN,
                 "height_before": TITLE_H_BEFORE, "height_after": TITLE_H_AFTER},
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
        print("  sub%d %s  %-10s %s -> %s  %s"
              % (s["subtype"], s["addr"], s["kind"], s["old_prefix"],
                 s["new_prefix"], s["note"]))
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

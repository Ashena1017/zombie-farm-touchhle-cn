#!/usr/bin/env python3
"""v24fix - user follow-ups after v23fix.

1) #2  the title now shows in full but sits too high.  The factory positions it
       with

           y = contentSize.height * 0.5 + (-6.0)      (sub9 0x76d0a..0x76d16)
           [title1 setPosition:(x, y)]                (sub9 0x76d50)

       and the label is anchored (0,0), so the text's TOP edge is at
       `y + height = 1.5*height - 6`.  Enlarging the box from 20 to 34 (v23)
       therefore pushed the top edge up by 21px.  Changing the `-6.0` VFP
       immediate to `-27.0` puts the top edge back at exactly its original
       height (1.5*34 - 27 = 24 == 1.5*20 - 6) while the box is still tall
       enough for the 24pt glyphs -- i.e. the clipping is gone and nothing
       moved.

           sub9 0x76d0e  c1ff180f (vmov.f32 d16, #-6.0)
                      -> c3ff1b0f (vmov.f32 d16, #-27.0)

2) #8  the Mausoleum caption should not be bold: repoint the font-name
       CFString from 'AmericanTypewriter-Bold' to 'AmericanTypewriter'.

           sub9 0x0d28fa  movw r3, #0x0ae8 -> #0x3718
                          (add r3, pc at 0x0d2904: 0x2d0ae8+0xd2908 = 0x3a33f0
                           "AmericanTypewriter-Bold"
                           -> 0x2d3718+0xd2908 = 0x3a6020 "AmericanTypewriter")
           sub6 0x11f1e4  literal 0x00348484 -> 0x0034b0b4
                          (add r3, pc, r0 at 0x11efd4: 0x11efdc+0x348484 =
                           0x467460 "AmericanTypewriter-Bold"
                           -> 0x11efdc+0x34b0b4 = 0x46a090 "AmericanTypewriter")
                          the only reader of that literal is 0x11efc0.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v23fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v24fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v24fix.report.json"

VMOV_SITE9 = 0x76D0E
VMOV_OLD = "c1ff180f"
VMOV_NEW = "c3ff1b0f"          # vmov.f32 d16, #-27.0 (found by bit-probing, verified below)
FONT_SITE9 = 0x0D28FA
FONT_OLD9 = "40f6e823"         # movw r3, #0xae8  (the constant in the image)
FONT_NEW9 = "43f21873"         # movw r3, #0x3718
FONT_CONST9_AFTER = 0x3718     # 0x3a6020 - (0x0d2904 + 4)
FONT_POOL6 = 0x11F1E4
FONT_OLD6 = "84843400"         # 0x00348484 -> 0x467460 'AmericanTypewriter-Bold'
FONT_NEW6 = "b4b03400"         # 0x0034b0b4 -> 0x46a090 'AmericanTypewriter'

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5), (0x1138C8, 0x1138F3),
        (0x1138F4, 0x113909)],
}


def thumb_movw(rd: int, imm16: int) -> bytes:
    imm4 = (imm16 >> 12) & 0xF
    i = (imm16 >> 11) & 1
    imm3 = (imm16 >> 8) & 0x7
    imm8 = imm16 & 0xFF
    return struct.pack("<HH", 0xF240 | (i << 10) | imm4,
                       (imm3 << 12) | (rd << 8) | imm8)


def check_vmov(code: bytes, addr: int, want: float) -> None:
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    ins = list(md.disasm(code, addr))
    if len(ins) != 1 or ins[0].mnemonic.split(".")[0] != "vmov":
        raise ValueError("%#x: %s is not a single vmov" % (addr, code.hex()))
    got = float(ins[0].op_str.split("#")[1].lstrip("+"))
    if abs(got - want) > 1e-9:
        raise ValueError("%#x: vmov decodes to %g, wanted %g" % (addr, got, want))


def check_movw(code: bytes, addr: int, want: int) -> None:
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    ins = list(md.disasm(code, addr))
    if len(ins) != 1 or ins[0].mnemonic.split(".")[0] != "movw" \
            or ins[0].operands[-1].imm != want:
        raise ValueError("%#x: %s is not movw #%#x" % (addr, code.hex(), want))


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

    # self-checks on the encodings before touching the image
    check_vmov(bytes.fromhex(VMOV_NEW), VMOV_SITE9, -27.0)
    check_vmov(bytes.fromhex(VMOV_OLD), VMOV_SITE9, -6.0)
    new9 = thumb_movw(3, FONT_CONST9_AFTER)
    if new9.hex() != FONT_NEW9:
        raise ValueError("movw encoder produced %s, expected %s"
                         % (new9.hex(), FONT_NEW9))
    check_movw(new9, FONT_SITE9, FONT_CONST9_AFTER)
    if struct.unpack("<I", bytes.fromhex(FONT_OLD6))[0] != 0x00348484 \
            or struct.unpack("<I", bytes.fromhex(FONT_NEW6))[0] != 0x0034B0B4:
        raise ValueError("sub6 literal constants are wrong")

    out = bytearray(original)
    applied: list[dict[str, Any]] = []

    def apply(subtype, addr, old_hex, new_hex, note):
        for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
            if addr < hi and lo < addr + len(old_hex) // 2:
                raise ValueError("sub%d %#x overlaps forbidden %#x" % (subtype, addr, lo))
        absolute = descriptors[subtype]["offset"] + slices[subtype].addr_to_file(addr)
        found = bytes(out[absolute:absolute + len(old_hex) // 2])
        if found != bytes.fromhex(old_hex):
            raise ValueError("sub%d %#x: expected %s, found %s"
                             % (subtype, addr, old_hex, found.hex()))
        if len(new_hex) != len(old_hex):
            raise ValueError("sub%d %#x: not width preserving" % (subtype, addr))
        out[absolute:absolute + len(new_hex) // 2] = bytes.fromhex(new_hex)
        applied.append({"subtype": subtype, "addr": f"{addr:#08x}",
                        "file_offset": absolute, "len": len(new_hex) // 2,
                        "old_prefix": old_hex, "new_prefix": new_hex, "note": note})

    apply(9, VMOV_SITE9, VMOV_OLD, VMOV_NEW,
          "#2 title1 position constant -6.0 -> -27.0 (keeps the text top where it was)")
    apply(9, FONT_SITE9, FONT_OLD9, FONT_NEW9,
          "#8 Mausoleum caption: AmericanTypewriter-Bold -> AmericanTypewriter")
    apply(6, FONT_POOL6, FONT_OLD6, FONT_NEW6,
          "#8 sub6 literal pool: same font swap")

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
        "#2": "text top = 1.5*boxHeight + C; with the v23 box of 34 the -6.0 "
              "constant put the top 21px too high, so it becomes -27.0 "
              "(1.5*34-27 == 1.5*20-6 == 24)",
        "#8": "the Mausoleum caption is de-bolded by pointing its fontName "
              "CFString at 'AmericanTypewriter' instead of "
              "'AmericanTypewriter-Bold' (sub9 instruction + sub6 literal pool)",
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
        print("  sub%d %s  %s -> %s  %s"
              % (s["subtype"], s["addr"], s["old_prefix"], s["new_prefix"], s["note"]))
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

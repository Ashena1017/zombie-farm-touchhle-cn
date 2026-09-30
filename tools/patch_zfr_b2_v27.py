#!/usr/bin/env python3
"""v27fix - user follow-up after v26fix.

v26 (C = -22.0, top = 1.5*34 - 22 = 29) still reads a touch LOW inside the
banner (user: up 2px more toward the visual centre).

One-byte nudge: C = -22.0 -> -20.0 moves the text top up by exactly 2px
(top = 1.5*34 - 20 = 31, i.e. +2px vs v26, still 14px below the v23
overshoot of 45).  The dimensions box stays 34px tall, so nothing clips.

    sub9 0x76d0e  c3ff160f (vmov.f32 d16, #-22.0)
               -> c3ff140f (vmov.f32 d16, #-20.0)

Both encodings verified with capstone before touching the image.
Width-preserving, no new stub, sub6 untouched (touchHLE runs sub9).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
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
INPUT_NAME = f"{BASE}.fixed-fonts-v26fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v27fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v27fix.report.json"

VMOV_SITE9 = 0x76D0E
VMOV_OLD = "c3ff160f"          # vmov.f32 d16, #-22.0 (v26)
VMOV_NEW = "c3ff140f"          # vmov.f32 d16, #-20.0

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5), (0x1138C8, 0x1138F3),
        (0x1138F4, 0x113909)],
}


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
    check_vmov(bytes.fromhex(VMOV_NEW), VMOV_SITE9, -20.0)
    check_vmov(bytes.fromhex(VMOV_OLD), VMOV_SITE9, -22.0)

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
          "#2 title1 position constant -22.0 -> -20.0 (nudge text top +2px toward visual centre)")

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
        "#2": "text top = 1.5*boxHeight + C; v26 (C=-22) still reads a touch "
              "low, so C becomes -20 (top = 1.5*34-20 = 31, +2px vs v26, box stays 34)",
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

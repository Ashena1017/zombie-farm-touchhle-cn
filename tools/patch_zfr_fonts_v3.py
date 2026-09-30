#!/usr/bin/env python3
"""Produce the v3 IPA: alert-box and Combiner fonts pinned to title 24 / body 18.

Design differences from the v2 patcher, all deliberate:

  * Absolute, not relative. v2 installed runtime wrappers that did `fontSize_ += 3`.
    v3 rewrites the font values at their source, so the result is idempotent and
    cannot compound with anything else.
  * No code caves. v2 hosted wrappers in the neutered bodies of ZFGuiLayer
    showRateIt / showTreeWorldPopUp. Those regions turned out to still receive
    inbound branches from live code (ZFAlertWindow showOkButtonIn:, three
    ZFZombieCombiner sites), so v3 does not write a single byte into them.
  * Width-preserving only. Every edit replaces N bytes with exactly N bytes at the
    same address, so no branch anywhere needs retargeting.

Built on .fixed.ipa. That baseline was verified to contain no live runtime writes
to CCLabel fontSize_ (+0x190): the only two `vstr s0,[r4,#0x190]` sites sit inside
helpers whose entry points the crash fix replaced with an immediate return.

Patch sites are supplied by PATCH_SITES, keyed by CPU subtype. Every entry carries
the bytes expected to be present, and the patcher refuses to run if any expectation
fails, so a stale site table cannot silently corrupt the binary.
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
    EXECUTABLE, fat_descriptors, outside_ranges_equal, parse_zip_layout,
    replace_zip_member, sha256, write_exclusive,
)

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v3.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v3.report.json"

TITLE_PT = 24.0
BODY_PT = 18.0

# Regions the patch must never touch: the neutered promotion-method bodies that
# still host the earlier round's helper network and receive live inbound branches.
FORBIDDEN = {
    6: [(0x1B464, 0x1B810)],
    9: [(0x14F6C, 0x151C0)],
}

# Every site is (address, expected_hex, new_hex, note). `expected_hex` is what the
# byte range must already contain; the patcher aborts if it does not, so a stale
# table cannot corrupt the binary. Lengths of expected/new always match.
#
# Two idioms appear here:
#   constant rewrite - the alert built by -initWithWindow: uses literal font sizes,
#     so the immediate that materialises the float is edited in place. ARM keeps the
#     value in `mov rX,#0xNN00000` (paired with a later `orr rX,rX,#0x40000000`);
#     Thumb keeps it in `movt rX,#0x41NN`.
#   argument pin - the alert built by +alertWindowInformative:withMessage:withFontSize:
#     receives its size as an int argument, converted by `vcvt.f32.s32`. There is no
#     constant to edit, so the conversion itself is replaced by `vmov.f32 s0,#imm`,
#     which is the same 4 bytes and leaves the following `vstr s0,[sp,#0xc]` intact.
#   body rebuild - the Simple and SimpleChoice factories do not keep the body label
#     that -initWithWindow: made; they build a fresh 250x180 one and re-install it
#     with setBody1:. Editing only -initWithWindow: would be overwritten on exactly
#     the paths the Combiner uses, so the rebuild constants are pinned too.
#
# In subtype 9 a single `movt r6` feeds both body1 and body2 (r6 stays live across
# the intervening msgSend), so one Thumb edit is equivalent to the two ARM ones.
PATCH_SITES: dict[int, list[tuple[int, str, str, str]]] = {
    6: [
        (0x0A040C, "1a36a0e3", "1c36a0e3",
         "initWithWindow: title mov r3,#0x1a00000 -> #0x1c00000 (20.0 -> 24.0)"),
        (0x0A0468, "1726a0e3", "1926a0e3",
         "initWithWindow: body mov r2,#0x1700000 -> #0x1900000 (15.0 -> 18.0) [1/2]"),
        (0x0A04BC, "1726a0e3", "1926a0e3",
         "initWithWindow: body mov r2,#0x1700000 -> #0x1900000 (15.0 -> 18.0) [2/2]"),
        (0x0A0F04, "c00ab8ee", "020ab3ee",
         "alertWindowInformative: body vcvt.f32.s32 s0,s0 -> vmov.f32 s0,#18.0"),
        (0x0A1048, "c00ab8ee", "080ab3ee",
         "alertWindowInformative: title vcvt.f32.s32 s0,s0 -> vmov.f32 s0,#24.0"),
        (0x0A16FC, "1726a0e3", "1926a0e3",
         "alertWindowSimple:...withWindow: body1 rebuild mov r2 (15.0 -> 18.0)"),
        (0x0A2190, "1736a0e3", "1936a0e3",
         "alertWindowSimpleChoice:...withWindow: body1 rebuild mov r3 (15.0 -> 18.0)"),
    ],
    9: [
        (0x0748E6, "c4f2a011", "c4f2c011",
         "initWithWindow: title movt r1,#0x41a0 -> #0x41c0 (20.0 -> 24.0)"),
        (0x074936, "c4f27016", "c4f29016",
         "initWithWindow: body movt r6,#0x4170 -> #0x4190 (15.0 -> 18.0, both bodies)"),
        (0x0750F8, "bbff0006", "b3ee020a",
         "alertWindowInformative: body vcvt.f32.s32 -> vmov.f32 s0,#18.0"),
        (0x075200, "bbff0006", "b3ee080a",
         "alertWindowInformative: title vcvt.f32.s32 -> vmov.f32 s0,#24.0"),
        (0x075788, "c4f27012", "c4f29012",
         "alertWindowSimple:...withWindow: body1 rebuild movt r2 (15.0 -> 18.0)"),
        (0x075FAA, "c4f27014", "c4f29014",
         "alertWindowSimpleChoice:...withWindow: body1 rebuild movt r4 (15.0 -> 18.0)"),
    ],
}

def slice_file_offset(sl: Any, addr: int) -> int:
    """Slice-local file offset for a virtual address, or raise."""
    off = sl.addr_to_file(addr)
    if off is None:
        raise ValueError(f"address {addr:#x} is not mapped in slice sub{sl.subtype}")
    return off


def check_forbidden(subtype: int, addr: int, length: int) -> None:
    for lo, hi in FORBIDDEN.get(subtype, []):
        if addr < hi and lo < addr + length:
            raise ValueError(
                f"sub{subtype} site {addr:#x}+{length} overlaps forbidden cave "
                f"{lo:#x}..{hi:#x}"
            )


def apply_sites(original: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    """Apply every PATCH_SITES entry to both slices of the FAT executable."""
    from audit_zfr_ipa import parse_fat  # local import: capstone-free path

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != set(descriptors) != {6, 9}:
        raise ValueError("FAT slice sets disagree between parsers")

    out = bytearray(original)
    applied: list[dict[str, Any]] = []
    for subtype in sorted(PATCH_SITES):
        sl = slices[subtype]
        base = descriptors[subtype]["offset"]
        for addr, expect_hex, new_hex, note in PATCH_SITES[subtype]:
            expect, new = bytes.fromhex(expect_hex), bytes.fromhex(new_hex)
            if len(expect) != len(new):
                raise ValueError(f"sub{subtype} {addr:#x}: width change is forbidden")
            check_forbidden(subtype, addr, len(new))
            local = slice_file_offset(sl, addr)
            absolute = base + local
            found = bytes(out[absolute : absolute + len(expect)])
            if found != expect:
                raise ValueError(
                    f"sub{subtype} {addr:#x}: expected {expect_hex}, found {found.hex()}"
                )
            out[absolute : absolute + len(new)] = new
            applied.append({
                "subtype": subtype, "addr": f"{addr:#08x}",
                "file_offset": absolute, "old": expect_hex, "new": new_hex,
                "note": note,
            })
    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    return bytes(out), applied


def verify_patched(original: bytes, patched: bytes,
                   applied: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-parse the patched FAT and confirm exactly the intended bytes moved."""
    from audit_zfr_ipa import parse_fat

    allowed = sorted((s["file_offset"], s["file_offset"] + len(bytes.fromhex(s["new"])))
                     for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("patched executable differs outside the intended sites")

    descriptors = {d["subtype"]: d for d in fat_descriptors(patched)}
    slices = {sl.subtype: sl for sl in parse_fat(patched)}
    readback: list[str] = []
    for site in applied:
        sl = slices[site["subtype"]]
        base = descriptors[site["subtype"]]["offset"]
        addr = int(site["addr"], 16)
        local = slice_file_offset(sl, addr)
        if base + local != site["file_offset"]:
            raise ValueError(f"sub{site['subtype']} {addr:#x}: offset moved after patch")
        got = patched[site["file_offset"]:
                      site["file_offset"] + len(bytes.fromhex(site["new"]))].hex()
        if got != site["new"]:
            raise ValueError(f"sub{site['subtype']} {addr:#x}: readback {got}")
        readback.append(f"sub{site['subtype']} {site['addr']} {got}")

    # Nothing may have been written into a cave, and the caves must be untouched.
    for subtype, ranges in FORBIDDEN.items():
        sl_o, sl_p = None, None
        for sl in parse_fat(original):
            if sl.subtype == subtype:
                sl_o = sl
        for sl in parse_fat(patched):
            if sl.subtype == subtype:
                sl_p = sl
        for lo, hi in ranges:
            a, b = slice_file_offset(sl_o, lo), slice_file_offset(sl_o, hi - 1) + 1
            if sl_o.data[a:b] != sl_p.data[a:b]:
                raise ValueError(f"sub{subtype} cave {lo:#x}..{hi:#x} was modified")
    return {"sites_verified": len(applied), "readback": readback,
            "caves_intact": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    parser.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    parser.add_argument("--dry-run", action="store_true",
                        help="verify every site and report, but write nothing")
    args = parser.parse_args()

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        original_exe = archive.read(EXECUTABLE)

    patched_exe, applied = apply_sites(original_exe)
    checks = verify_patched(original_exe, patched_exe, applied)

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "title_pt": TITLE_PT, "body_pt": BODY_PT,
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source),
                  "executable_sha256": sha256(original_exe)},
        "sites": applied,
        "executable_checks": checks,
        "forbidden_regions": {str(k): [[f"{lo:#x}", f"{hi:#x}"] for lo, hi in v]
                              for k, v in FORBIDDEN.items()},
    }

    if args.dry_run:
        report["dry_run"] = True
        print(json.dumps(report, indent=2))
        return 0

    output, zip_meta = replace_zip_member(source, patched_exe)
    if len(output) != len(source):
        raise ValueError("output archive changed size")
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        if archive.read(EXECUTABLE) != patched_exe:
            raise ValueError("round-trip of the patched member failed")
        if archive.testzip() is not None:
            raise ValueError("output archive failed testzip()")

    write_exclusive(args.output, output)
    report["zip"] = zip_meta
    report["output"] = {"name": args.output.name, "size": len(output),
                        "sha256": sha256(output),
                        "executable_sha256": sha256(patched_exe)}
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {args.output.name}  ({len(output)} bytes)")
    for site in applied:
        print(f"  sub{site['subtype']} {site['addr']} {site['old']} -> "
              f"{site['new']}  {site['note']}")
    print(f"report: {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

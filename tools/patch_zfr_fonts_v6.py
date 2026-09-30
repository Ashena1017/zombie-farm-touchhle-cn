#!/usr/bin/env python3
"""Produce the v6 IPA: enlarge the market "unlock item early" dialog body text.

Reported problem (screenshot 1): the confirmation dialog shown by
`ZFMarketMenu -unlockItem:` ("Unlock Item" / "Are you sure you want to unlock
%@ early?" / "Cost: %d") still renders its body at the original small size,
even though v3 pinned every alert box to title 24 / body 18.

Why v3/v5 miss it: this dialog does not use the body label that
`-initWithWindow:` created. It builds a **fresh** label and installs it with
`setBody1:`:

    ARM   0x6a49c   mov  r2, #0x1600000        ; 14.0
          0x6a4bc   orr  r2, r2, #0x40000000
          0x6a4c0   str  r2, [sp, #0xc]        ; fontSize slot
          0x6a4a0/0x6a4cc  labelWithString:...:fontSize: -> setBody1:

    Thumb 0x4d6f4   movt r3, #0x4160           ; 14.0
          0x4d6fc   str  r3, [sp, #0xc]
          0x4d704   blx  objc_msgSend

This is the same "factory rebuild" idiom as Simple/SimpleChoice, which v3
already handles; the market dialog simply had its own copy of it.

v6 rewrites those two immediates 14.0 -> 18.0, matching the body tier used
everywhere else. Both edits are single width-preserving immediates, decoded back
to a float before being accepted.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v5.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v6.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v6.report.json"

# The v4 helper network. v6 must not disturb it.
FORBIDDEN = {6: [(0x1B464, 0x1B810)], 9: [(0x14F6C, 0x151C0)]}

TARGET_PT = 18.0

# (addr, expected_hex, new_hex, note)
PATCH_SITES: dict[int, list[tuple[int, str, str, str]]] = {
    6: [
        (0x6A49C, "1626a0e3", "1926a0e3",
         "ZFMarketMenu -unlockItem: body label 14.0 -> 18.0 "
         "(mov r2,#0x1600000 -> #0x1900000)"),
    ],
    9: [
        (0x4D6F4, "c4f26013", "c4f29013",
         "ZFMarketMenu -unlockItem: body label 14.0 -> 18.0 "
         "(movt r3,#0x4160 -> #0x4190)"),
    ],
}


def slice_file_offset(sl: Any, addr: int) -> int:
    off = sl.addr_to_file(addr)
    if off is None:
        raise ValueError(f"address {addr:#x} is not mapped in slice sub{sl.subtype}")
    return off


def check_forbidden(subtype: int, addr: int, length: int) -> None:
    for lo, hi in FORBIDDEN.get(subtype, []):
        if addr < hi and lo < addr + length:
            raise ValueError(
                f"sub{subtype} site {addr:#x}+{length} overlaps the v4 helper "
                f"region {lo:#x}..{hi:#x}"
            )


def decode_arm_mov_imm(raw: bytes) -> int:
    w = struct.unpack_from("<I", raw, 0)[0]
    if (w & 0x0FE00000) != 0x03A00000:
        raise ValueError(f"not an ARM mov-immediate: {raw.hex()}")
    rot = ((w >> 8) & 0xF) * 2
    imm8 = w & 0xFF
    return ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8


def decode_thumb_movt(raw: bytes) -> int:
    f, s2 = struct.unpack_from("<HH", raw, 0)
    if (f & 0xFBF0) != 0xF2C0 or (s2 & 0x8000) != 0:
        raise ValueError(f"not a Thumb movt: {raw.hex()}")
    return (((f & 0xF) << 12) | (((f >> 10) & 1) << 11)
            | (((s2 >> 12) & 7) << 8) | (s2 & 0xFF))


def verify_replacement_float(subtype: int, new: bytes) -> str:
    """Decode the replacement and prove it builds 18.0."""
    if subtype == 6:
        val = decode_arm_mov_imm(new)
        built = struct.unpack("<f", struct.pack("<I", val | 0x40000000))[0]
    else:
        imm16 = decode_thumb_movt(new)
        built = struct.unpack("<f", struct.pack("<I", imm16 << 16))[0]
    if abs(built - TARGET_PT) > 1e-6:
        raise ValueError(f"sub{subtype}: replacement decodes to {built}, "
                         f"want {TARGET_PT}")
    return f"{built:g}"


def apply_sites(original: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    from audit_zfr_ipa import parse_fat

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
            built = verify_replacement_float(subtype, new)
            absolute = base + slice_file_offset(sl, addr)
            found = bytes(out[absolute:absolute + len(expect)])
            if found != expect:
                raise ValueError(
                    f"sub{subtype} {addr:#x}: expected {expect_hex}, found {found.hex()}"
                )
            out[absolute:absolute + len(new)] = new
            applied.append({
                "subtype": subtype, "addr": f"{addr:#08x}",
                "file_offset": absolute, "old": expect_hex, "new": new_hex,
                "float": built, "note": note,
            })
    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    return bytes(out), applied


def verify_patched(original: bytes, patched: bytes,
                   applied: list[dict[str, Any]]) -> dict[str, Any]:
    from audit_zfr_ipa import parse_fat

    allowed = sorted((s["file_offset"], s["file_offset"] + len(bytes.fromhex(s["new"])))
                     for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("patched executable differs outside the intended sites")

    descriptors = {d["subtype"]: d for d in fat_descriptors(patched)}
    slices = {sl.subtype: sl for sl in parse_fat(patched)}
    readback = []
    for site in applied:
        sl = slices[site["subtype"]]
        base = descriptors[site["subtype"]]["offset"]
        addr = int(site["addr"], 16)
        if base + slice_file_offset(sl, addr) != site["file_offset"]:
            raise ValueError(f"sub{site['subtype']} {addr:#x}: offset moved")
        got = patched[site["file_offset"]:
                      site["file_offset"] + len(bytes.fromhex(site["new"]))].hex()
        if got != site["new"]:
            raise ValueError(f"sub{site['subtype']} {addr:#x}: readback {got}")
        readback.append(f"sub{site['subtype']} {site['addr']} {got} ({site['float']})")

    for subtype, ranges in FORBIDDEN.items():
        sl_o = next(s for s in parse_fat(original) if s.subtype == subtype)
        sl_p = next(s for s in parse_fat(patched) if s.subtype == subtype)
        for lo, hi in ranges:
            a = slice_file_offset(sl_o, lo)
            b = slice_file_offset(sl_o, hi - 1) + 1
            if sl_o.data[a:b] != sl_p.data[a:b]:
                raise ValueError(
                    f"sub{subtype} v4 helper region {lo:#x}..{hi:#x} was modified"
                )
    return {"sites_verified": len(applied), "readback": readback,
            "v4_helper_region_intact": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    parser.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        original_exe = archive.read(EXECUTABLE)

    patched_exe, applied = apply_sites(original_exe)
    checks = verify_patched(original_exe, patched_exe, applied)

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "purpose": "enlarge the market 'unlock item early' confirmation body text "
                   "from 14.0 to 18.0 so it matches the rest of the alert tier",
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
              f"{site['new']}  [{site['float']}]  {site['note']}")
    print(f"report: {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Produce the v5 IPA: bring every dedicated ZFAlertWindow subclass dialog to
title 24 / body 18.

v3 pinned the ZFAlertWindow *base* class (13 sites) and v4 repaired the helper
network. That left the subclasses, which build their own labels with their own
hardcoded font constants and never pass through the base-class sites:

    ZFAlertWindowQuestComplete   -initWithQuest:                  title 20 -> 24
    ZFAlertWindowQuest           -initWithQuest:                  title 20 -> 24
    ZFAlertWindowFlurryOffer     -initWithWindow:   (override!)   title 20 -> 24
    ZFAlertWindowBrainSpinner    -displayResult                   title 20 -> 24
    ZFAlertWindowFriendsList     -init  (two labels)              title 20 -> 24
    ZFAlertWindowGiftReceive     -initWithGifts:                  title 20 -> 24
    ZFAlertWindowGiftSelection   -initWithLevel:                  title 20 -> 24
    ZFAlertWindowPromo           -initWithWindow:withDictionary:  body  15 -> 18
    ZFAlertWindowPromo           -display                         body  15 -> 18

Each edit is a single width-preserving immediate rewrite:

  ARM   `mov rX,#0x1a00000` -> `mov rX,#0x1c00000`   (20.0 -> 24.0)
  Thumb `movt rX,#0x41a0`   -> `movt rX,#0x41c0`     (20.0 -> 24.0)

The float is assembled as `mov/movw` (low bits) + `orr #0x40000000` on ARM, and
`movw` + `movt` on Thumb, so only the immediate that carries the mantissa needs
to change. Every replacement is decoded back to a float before being accepted,
because the ARM immediate is a rotated 8-bit field and a wrong rotate would
silently produce a different value.

Not touched, deliberately:
  * `ZFAlertWindowFlurryOffer`'s second label, `ZFAlertWindowBrainSpinner -init`,
    `ZFAlertWindowDailyBonus -init`, `ZFAlertWindowGoldenDice -init` - already 24.0.
  * The slide-in family (`alertWindowSlideInInformative*`) and
    `ZFAlertWindowStorageItem` - body is already 18.0; their title is 19.0, which
    is out of the 15/20 in-scope set and would change a deliberately distinct
    visual tier.
  * `ZFGuiLayer displayToolTip:` - 26.0, shared by every tooltip in the game.

Invariants enforced here: width-preserving, expected-bytes verified, decoded-back
float equality, no overlap with the v4 cave regions, and a whole-executable
comparison proving nothing outside the declared sites moved.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v4.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v5.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v5.report.json"

# v4's repaired helper network lives here; v5 must not disturb it.
FORBIDDEN = {6: [(0x1B464, 0x1B810)], 9: [(0x14F6C, 0x151C0)]}

# (addr, expected_hex, new_hex, note)
PATCH_SITES: dict[int, list[tuple[int, str, str, str]]] = {
    6: [
        (0x16682C, "1a36a0e3", "1c36a0e3",
         "ZFAlertWindowFlurryOffer -initWithWindow: title 20.0 -> 24.0"),
        (0x16E7BC, "1a36a0e3", "1c36a0e3",
         "ZFAlertWindowQuest -initWithQuest: title 20.0 -> 24.0"),
        (0x16F240, "1ab6a0e3", "1cb6a0e3",
         "ZFAlertWindowQuestComplete -initWithQuest: title 20.0 -> 24.0"),
        (0x1A3950, "1a36a0e3", "1c36a0e3",
         "ZFAlertWindowFriendsList -init title 20.0 -> 24.0 [1/2]"),
        (0x1A3C00, "1a36a0e3", "1c36a0e3",
         "ZFAlertWindowFriendsList -init title 20.0 -> 24.0 [2/2]"),
        (0x1A81D8, "1a36a0e3", "1c36a0e3",
         "ZFAlertWindowGiftReceive -initWithGifts: title 20.0 -> 24.0"),
        (0x1A9654, "1a36a0e3", "1c36a0e3",
         "ZFAlertWindowGiftSelection -initWithLevel: title 20.0 -> 24.0"),
        (0x1B2020, "1726a0e3", "1926a0e3",
         "ZFAlertWindowPromo -initWithWindow:withDictionary: body 15.0 -> 18.0"),
        (0x1B3528, "1726a0e3", "1926a0e3",
         "ZFAlertWindowPromo -display body 15.0 -> 18.0"),
        (0x252B60, "1a96a0e3", "1c96a0e3",
         "ZFAlertWindowBrainSpinner -displayResult title 20.0 -> 24.0"),
    ],
    9: [
        (0x10776C, "c4f2a010", "c4f2c010",
         "ZFAlertWindowFlurryOffer -initWithWindow: title 20.0 -> 24.0"),
        (0x10D090, "c4f2a016", "c4f2c016",
         "ZFAlertWindowQuest -initWithQuest: title 20.0 -> 24.0"),
        (0x10DA84, "c4f2a010", "c4f2c010",
         "ZFAlertWindowQuestComplete -initWithQuest: title 20.0 -> 24.0"),
        (0x134524, "c4f2a010", "c4f2c010",
         "ZFAlertWindowFriendsList -init title 20.0 -> 24.0 [1/2]"),
        (0x13478A, "c4f2a010", "c4f2c010",
         "ZFAlertWindowFriendsList -init title 20.0 -> 24.0 [2/2]"),
        (0x137B84, "c4f2a010", "c4f2c010",
         "ZFAlertWindowGiftReceive -initWithGifts: title 20.0 -> 24.0"),
        (0x138B84, "c4f2a010", "c4f2c010",
         "ZFAlertWindowGiftSelection -initWithLevel: title 20.0 -> 24.0"),
        (0x14007C, "c4f27012", "c4f29012",
         "ZFAlertWindowPromo -display body 15.0 -> 18.0"),
        (0x1B35AC, "c4f2a016", "c4f2c016",
         "ZFAlertWindowBrainSpinner -displayResult title 20.0 -> 24.0"),
    ],
}

# What each replacement must evaluate to, for the decode-back gate.
EXPECT_FLOAT = {0x1C00000: 24.0, 0x1900000: 18.0}
EXPECT_FLOAT_THUMB = {0x41C0: 24.0, 0x4190: 18.0}


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


def decode_arm_mov_imm(raw: bytes) -> tuple[int, int]:
    w = struct.unpack_from("<I", raw, 0)[0]
    if (w & 0x0FE00000) != 0x03A00000:
        raise ValueError(f"not an ARM mov-immediate: {raw.hex()}")
    rot = ((w >> 8) & 0xF) * 2
    imm8 = w & 0xFF
    val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8
    return (w >> 12) & 0xF, val


def decode_thumb_movt(raw: bytes) -> tuple[int, int]:
    f, s2 = struct.unpack_from("<HH", raw, 0)
    if (f & 0xFBF0) != 0xF2C0 or (s2 & 0x8000) != 0:
        raise ValueError(f"not a Thumb movt: {raw.hex()}")
    imm4 = f & 0xF
    i = (f >> 10) & 1
    imm3 = (s2 >> 12) & 0x7
    rd = (s2 >> 8) & 0xF
    imm8 = s2 & 0xFF
    return rd, (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8


def verify_replacement_float(subtype: int, new: bytes, note: str) -> str:
    """Decode the replacement and prove it builds 24.0 or 18.0."""
    if subtype == 6:
        _, val = decode_arm_mov_imm(new)
        built = struct.unpack("<f", struct.pack("<I", val | 0x40000000))[0]
        want = EXPECT_FLOAT.get(val)
    else:
        _, imm16 = decode_thumb_movt(new)
        built = struct.unpack("<f", struct.pack("<I", imm16 << 16))[0]
        want = EXPECT_FLOAT_THUMB.get(imm16)
    if want is None:
        raise ValueError(f"sub{subtype}: {note} produced unexpected float {built}")
    if abs(built - want) > 1e-6:
        raise ValueError(f"sub{subtype}: {note} decodes to {built}, want {want}")
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
            built = verify_replacement_float(subtype, new, note)
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

    # v4's helper region must be byte-identical
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
        "purpose": "extend title 24 / body 18 to the dedicated ZFAlertWindow "
                   "subclass dialogs",
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

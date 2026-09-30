#!/usr/bin/env python3
"""DIAGNOSTIC build: tag each of the three code paths that can manufacture a
zeroed quest `progress` array with a distinct sentinel, so that ONE game run
identifies which path actually fires.

Background (see ZFR_图3_任务计数_深挖报告.md):

  saveGame.bin2 quest section = uint32 count, then
      uint32 ID, uint32 reqCount, reqCount * uint32 progress
  `GameData -addUserData:` writes `progress` VERBATIM from
  `gameData.currentQuests[i][@"progress"]`.  A probe proved the whole
  load->save round trip is byte faithful (8 non-zero values survived a clean
  exit untouched), yet after PLAYING (plow + invade) every value came back 0.

  Exactly three code paths build the literal `@[@0,@0,@0]` progress array:

    A  ZFQuestMan -addQuestWithID:              new quest dict (hardcoded)
    B  ZFQuestNotification -requirementUpdated: zero-overwrite branch
       (fires when the matching dict's `progress` is nil or empty)
    C  ZFQuestMan -restoreQuestsFromSave        zero-overwrite branch
       (same condition, once per dict in currentQuests)

  This build writes 7 / 8 / 9 instead of 0 at A / B / C respectively.
  Reading the resulting save tells us which path produced the zeros:

      progress == 7  -> A fired (quest dicts were re-created)
      progress == 8  -> B fired (requirementUpdated: saw nil/empty progress)
      progress == 9  -> C fired (restoreQuestsFromSave saw nil/empty progress)
      progress == 0  -> none of A/B/C; the dicts were emptied elsewhere
      probe value    -> that dict was never touched

  Width preserving: every edit is a single ARM `mov r2,#imm` / Thumb
  `movs r2,#imm` immediate.  Diagnostic only - not a fix.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v6.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v7diag.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v7diag.report.json"

# The v4 codex-injected localisation helper network must never be touched.
FORBIDDEN = {6: [(0x1B464, 0x1B810)], 9: [(0x14F6C, 0x151C0)]}

A, B, C = 7, 8, 9

# (addr, expected_hex, sentinel, note)
SITES: dict[int, list[tuple[int, str, int, str]]] = {
    6: [
        (0x16C5B4, "0020a0e3", A, "A addQuestWithID: numberWithInt:0 #1"),
        (0x16C5D0, "0020a0e3", A, "A addQuestWithID: numberWithInt:0 #2"),
        (0x16C5E4, "0020a0e3", A, "A addQuestWithID: numberWithInt:0 #3"),
        (0x16A8C8, "0020a0e3", B, "B requirementUpdated: zero-branch #1"),
        (0x16A8E4, "0020a0e3", B, "B requirementUpdated: zero-branch #2"),
        (0x16A8F8, "0020a0e3", B, "B requirementUpdated: zero-branch #3"),
        (0x16E1A4, "0020a0e3", C, "C restoreQuestsFromSave zero-branch #1"),
        (0x16E1C4, "0020a0e3", C, "C restoreQuestsFromSave zero-branch #2"),
        (0x16E1D8, "0020a0e3", C, "C restoreQuestsFromSave zero-branch #3"),
    ],
    9: [
        (0x10B9C6, "0022", A, "A addQuestWithID: numberWithInt:0 #1"),
        (0x10B9DE, "0022", A, "A addQuestWithID: numberWithInt:0 #2"),
        (0x10B9EC, "0022", A, "A addQuestWithID: numberWithInt:0 #3"),
        (0x10A3FE, "0022", B, "B requirementUpdated: zero-branch #1"),
        (0x10A410, "0022", B, "B requirementUpdated: zero-branch #2"),
        (0x10A41C, "0022", B, "B requirementUpdated: zero-branch #3"),
        (0x10CD18, "0022", C, "C restoreQuestsFromSave zero-branch #1"),
        (0x10CD3E, "0022", C, "C restoreQuestsFromSave zero-branch #2"),
        (0x10CD4A, "0022", C, "C restoreQuestsFromSave zero-branch #3"),
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
                f"sub{subtype} site {addr:#x}+{length} overlaps the helper "
                f"region {lo:#x}..{hi:#x}")


def build_replacement(subtype: int, sentinel: int) -> bytes:
    if subtype == 6:
        # mov r2, #imm   (cond=AL, opcode 0xE3A02000, rotate=0)
        return struct.pack("<I", 0xE3A02000 | sentinel)
    # Thumb: movs r2, #imm8  -> 0x2200 | imm8
    if not (0 <= sentinel <= 0xFF):
        raise ValueError("thumb movs immediate out of range")
    return struct.pack("<H", 0x2200 | sentinel)


def verify_replacement(subtype: int, raw: bytes, sentinel: int) -> None:
    if subtype == 6:
        w = struct.unpack_from("<I", raw, 0)[0]
        if (w & 0x0FE00000) != 0x03A00000 or (w & 0xF000) != 0x2000:
            raise ValueError(f"not `mov r2,#imm`: {raw.hex()}")
        rot = ((w >> 8) & 0xF) * 2
        imm8 = w & 0xFF
        val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8
        if val != sentinel:
            raise ValueError(f"decodes to {val}, want {sentinel}")
    else:
        h = struct.unpack_from("<H", raw, 0)[0]
        if (h & 0xFF00) != 0x2200:
            raise ValueError(f"not `movs r2,#imm8`: {raw.hex()}")
        if (h & 0xFF) != sentinel:
            raise ValueError(f"decodes to {h & 0xFF}, want {sentinel}")


def apply_sites(original: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    from audit_zfr_ipa import parse_fat

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != set(descriptors) or set(slices) != {6, 9}:
        raise ValueError("unexpected FAT slice set")

    out = bytearray(original)
    applied: list[dict[str, Any]] = []
    for subtype in sorted(SITES):
        sl = slices[subtype]
        base = descriptors[subtype]["offset"]
        for addr, expect_hex, sentinel, note in SITES[subtype]:
            expect = bytes.fromhex(expect_hex)
            new = build_replacement(subtype, sentinel)
            if len(expect) != len(new):
                raise ValueError(f"sub{subtype} {addr:#x}: width change forbidden")
            check_forbidden(subtype, addr, len(new))
            verify_replacement(subtype, new, sentinel)
            absolute = base + slice_file_offset(sl, addr)
            found = bytes(out[absolute:absolute + len(expect)])
            if found != expect:
                raise ValueError(
                    f"sub{subtype} {addr:#x}: expected {expect_hex}, found {found.hex()}")
            out[absolute:absolute + len(new)] = new
            applied.append({
                "subtype": subtype, "addr": f"{addr:#08x}", "path": note[0],
                "file_offset": absolute, "old": expect_hex, "new": new.hex(),
                "sentinel": sentinel, "note": note,
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
        verify_replacement(site["subtype"],
                           bytes.fromhex(got), site["sentinel"])

    for subtype, ranges in FORBIDDEN.items():
        sl_o = next(s for s in parse_fat(original) if s.subtype == subtype)
        sl_p = next(s for s in parse_fat(patched) if s.subtype == subtype)
        for lo, hi in ranges:
            a = slice_file_offset(sl_o, lo)
            b = slice_file_offset(sl_o, hi - 1) + 1
            if sl_o.data[a:b] != sl_p.data[a:b]:
                raise ValueError(
                    f"sub{subtype} helper region {lo:#x}..{hi:#x} was modified")

    counts = {}
    for s in applied:
        counts[s["path"]] = counts.get(s["path"], 0) + 1
    return {"sites_verified": len(applied), "sites_per_path": counts,
            "helper_region_intact": True}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    ap.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    ap.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        original_exe = archive.read(EXECUTABLE)

    patched_exe, applied = apply_sites(original_exe)
    checks = verify_patched(original_exe, patched_exe, applied)

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "DIAGNOSTIC (not a fix)",
        "purpose": "tag the three @[@0,@0,@0] progress-array builders with "
                   "sentinels 7/8/9 so one game run identifies which one zeroes "
                   "the quest progress that fails to persist",
        "legend": {"A": "ZFQuestMan -addQuestWithID:", "B": "requirementUpdated: zero branch",
                   "C": "restoreQuestsFromSave zero branch"},
        "input": {"name": args.input.name, "size": len(source), "sha256": sha256(source),
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
                        "sha256": sha256(output), "executable_sha256": sha256(patched_exe)}
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {args.output.name}  ({len(output)} bytes)")
    for site in applied:
        print(f"  sub{site['subtype']} {site['addr']} {site['old']} -> "
              f"{site['new']}  [{site['sentinel']}]  {site['note']}")
    print(f"report: {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""DIAGNOSTIC build #3 (v9diag): instrument the NORMAL write path of
ZFQuestNotification -requirementUpdated:.

Why the first two diagnostics saw nothing
-----------------------------------------
A full scan of both slices proved only five functions ever touch the
`currentQuests[i][@"progress"]` key.  v7diag tagged the three array builders
(A/B/C) and v8diag additionally tagged the two plain-zero writers (D/E).  Both
runs zeroed every probed quest and showed NO sentinel at all.

The missing writer is the *normal* branch of `requirementUpdated:`:

    [array replaceObjectAtIndex:idx withObject:@(countCurrent)]
                                  ^^^^^^^^^^^^^^^^^^^
It writes the notification's own `countCurrent` - no literal 0, no @[@0,@0,@0],
therefore invisible to every sentinel so far.

`requirementUpdated:` is registered on EVERY ZFQuestNotification with
object=nil, so a single requirement increment makes every live notification run
its handler and rewrite ITS OWN dict from ITS OWN `countCurrent`.  If the live
notifications have been rebuilt from Quests.plist (countCurrent = 0) while the
dicts still hold saved progress, ONE increment zeroes EVERY quest dict - which
is exactly what the probe runs show.

This build forces that value to 3:

    ARM   0x16aadc / 0x16ab20   mov r2, r0        -> mov r2, #3
    Thumb 0x10a568 / 0x10a598   mov r2, r0 (4602) -> movs r2, #3 (2203)

Reading the result:

    value 3  -> the normal path ran and rewrote the dict from countCurrent;
                since the unpatched run produced 0, countCurrent was 0
                => stale notifications confirmed
    value 0  -> the normal path never ran; the zeroing is elsewhere
    4/5/7/8/9 -> D/E/A/B/C (should not happen)

All v8diag sentinels are kept.  Width preserving, both slices.
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
OUTPUT_NAME = f"{BASE}.fixed-fonts-v9diag.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v9diag.report.json"

FORBIDDEN = {6: [(0x1B464, 0x1B810)], 9: [(0x14F6C, 0x151C0)]}

A, B, C, D, E, F = 7, 8, 9, 5, 4, 3

# kind 0 = `mov r2,#0` / `movs r2,#0`   (replace immediate)
# kind 1 = `mov r2,r0` / `mov r2,r0`   (replace register copy with immediate)
SITES: dict[int, list[tuple[int, str, int, int, str]]] = {
    6: [
        (0x16C5B4, "0020a0e3", A, 0, "A addQuestWithID: zeros #1"),
        (0x16C5D0, "0020a0e3", A, 0, "A addQuestWithID: zeros #2"),
        (0x16C5E4, "0020a0e3", A, 0, "A addQuestWithID: zeros #3"),
        (0x16A8C8, "0020a0e3", B, 0, "B requirementUpdated: zero-branch #1"),
        (0x16A8E4, "0020a0e3", B, 0, "B requirementUpdated: zero-branch #2"),
        (0x16A8F8, "0020a0e3", B, 0, "B requirementUpdated: zero-branch #3"),
        (0x16E1A4, "0020a0e3", C, 0, "C restoreQuestsFromSave zero-branch #1"),
        (0x16E1C4, "0020a0e3", C, 0, "C restoreQuestsFromSave zero-branch #2"),
        (0x16E1D8, "0020a0e3", C, 0, "C restoreQuestsFromSave zero-branch #3"),
        (0x186ECC, "0020a0e3", D, 0, "D addUserData: out-of-range/NSNull"),
        (0x187E34, "0020a0e3", E, 0, "E readUserData: progress padding"),
        (0x16AADC, "0020a0e1", F, 1, "F requirementUpdated: replace value"),
        (0x16AB20, "0020a0e1", F, 1, "F requirementUpdated: addObject value"),
    ],
    9: [
        (0x10B9C6, "0022", A, 0, "A addQuestWithID: zeros #1"),
        (0x10B9DE, "0022", A, 0, "A addQuestWithID: zeros #2"),
        (0x10B9EC, "0022", A, 0, "A addQuestWithID: zeros #3"),
        (0x10A3FE, "0022", B, 0, "B requirementUpdated: zero-branch #1"),
        (0x10A410, "0022", B, 0, "B requirementUpdated: zero-branch #2"),
        (0x10A41C, "0022", B, 0, "B requirementUpdated: zero-branch #3"),
        (0x10CD18, "0022", C, 0, "C restoreQuestsFromSave zero-branch #1"),
        (0x10CD3E, "0022", C, 0, "C restoreQuestsFromSave zero-branch #2"),
        (0x10CD4A, "0022", C, 0, "C restoreQuestsFromSave zero-branch #3"),
        (0x11F53C, "0022", D, 0, "D addUserData: out-of-range/NSNull"),
        (0x120074, "0022", E, 0, "E readUserData: progress padding"),
        (0x10A568, "0246", F, 1, "F requirementUpdated: replace value"),
        (0x10A598, "0246", F, 1, "F requirementUpdated: addObject value"),
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


def build_replacement(subtype: int, sentinel: int, kind: int) -> bytes:
    if subtype == 6:
        return struct.pack("<I", 0xE3A02000 | sentinel)
    return struct.pack("<H", 0x2200 | sentinel)


def verify_immediate(subtype: int, raw: bytes, sentinel: int) -> None:
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
        if (h & 0xFF00) != 0x2200 or (h & 0xFF) != sentinel:
            raise ValueError(f"not `movs r2,#{sentinel}`: {raw.hex()}")


def verify_original(subtype: int, raw: bytes, kind: int) -> None:
    if kind == 0:
        if subtype == 6:
            if struct.unpack_from("<I", raw, 0)[0] != 0xE3A02000:
                raise ValueError(f"expected `mov r2,#0`, got {raw.hex()}")
        else:
            if struct.unpack_from("<H", raw, 0)[0] != 0x2200:
                raise ValueError(f"expected `movs r2,#0`, got {raw.hex()}")
    else:
        if subtype == 6:
            if struct.unpack_from("<I", raw, 0)[0] != 0xE1A02000:
                raise ValueError(f"expected `mov r2,r0`, got {raw.hex()}")
        else:
            if struct.unpack_from("<H", raw, 0)[0] != 0x4602:
                raise ValueError(f"expected `mov r2,r0`, got {raw.hex()}")


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
        for addr, expect_hex, sentinel, kind, note in SITES[subtype]:
            expect = bytes.fromhex(expect_hex)
            new = build_replacement(subtype, sentinel, kind)
            if len(expect) != len(new):
                raise ValueError(f"sub{subtype} {addr:#x}: width change forbidden")
            check_forbidden(subtype, addr, len(new))
            verify_original(subtype, expect, kind)
            verify_immediate(subtype, new, sentinel)
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
        verify_immediate(site["subtype"], bytes.fromhex(got), site["sentinel"])

    for subtype, ranges in FORBIDDEN.items():
        sl_o = next(s for s in parse_fat(original) if s.subtype == subtype)
        sl_p = next(s for s in parse_fat(patched) if s.subtype == subtype)
        for lo, hi in ranges:
            a = slice_file_offset(sl_o, lo)
            b = slice_file_offset(sl_o, hi - 1) + 1
            if sl_o.data[a:b] != sl_p.data[a:b]:
                raise ValueError(
                    f"sub{subtype} helper region {lo:#x}..{hi:#x} was modified")

    counts: dict[str, int] = {}
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
        "kind": "DIAGNOSTIC #3 (not a fix)",
        "purpose": "instrument the normal `@(countCurrent)` write of "
                   "requirementUpdated: (value forced to 3), which is the only "
                   "dict writer with no literal 0 and hence no earlier sentinel",
        "legend": {
            "A=7": "addQuestWithID: hardcoded zeros",
            "B=8": "requirementUpdated: zero branch",
            "C=9": "restoreQuestsFromSave zero branch",
            "D=5": "addUserData: out-of-range/NSNull fallback",
            "E=4": "readUserData: progress padding",
            "F=3": "requirementUpdated: NORMAL path value (was countCurrent)",
        },
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
    print(f"  ipa sha256 = {report['output']['sha256']}")
    for site in applied:
        print(f"  sub{site['subtype']} {site['addr']} {site['old']} -> "
              f"{site['new']}  [{site['sentinel']}]  {site['note']}")
    print(f"report: {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

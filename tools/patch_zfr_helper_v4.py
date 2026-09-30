#!/usr/bin/env python3
"""Produce the v4 IPA: repair the neutered localisation/font helper network.

Background
----------
An earlier round (codex, "V54-V56") implemented Chinese entity-name rebuilding by
injecting hand-written ARM/Thumb into the bodies of two ZFGuiLayer promotion
methods that were no longer reachable:

    showRateIt           ARM 0x1b464   Thumb 0x14f6c   (delta +4.0)
    showTreeWorldPopUp   ARM 0x1b688   Thumb 0x15110   (delta +3.0)

Each helper does two jobs in one call: bump `fontSize_` and re-issue
`setString:` with a localised string handed over in r2.

A later crash fix (2026-08-28) replaced those two *entry points* with an
immediate return, because ObjC dispatch of `showRateIt` / `showTreeWorldPopUp`
was reaching the helper with a ZFGuiLayer in r0 and treating it as a CCLabel.
That stopped the panic but silently killed both jobs, because every wrapper
calls the entry, not the body.

What v4 changes
---------------
1. RETARGET - every intra-cave `bl` aimed at an entry is redirected to that
   entry's body (ARM entry+8, Thumb entry+4). The entries stay `bx lr`, so
   ObjC dispatch is still crash-safe, but the wrapper network works again and
   the Chinese name rebuild comes back.

2. DELTA ZERO - v3 pinned the creation constants to absolute 24/18. With the
   helpers alive again, their `fontSize_ += 4.0` / `+= 3.0` would render 28/22.
   Each `vadd.f32 s0, s0, s2` is therefore replaced by a redundant
   `vldr s0, [r4, #0x190]`, which loads the same value straight back so the
   following `vstr s0, [r4, #0x190]` stores it unchanged. Both forms are 4
   bytes, and the replacement encoding already appears verbatim at the top of
   the very same helper.

So the helper keeps its localisation job and loses its sizing job.

Invariants enforced here
------------------------
* Every edit is width-preserving and confined to the two cave regions.
* The four entry words are never touched, and are re-checked afterwards to
  still decode as an immediate return.
* Every retargeted branch is re-decoded from the patched bytes and must land
  exactly on the intended body address.
* Every site names the bytes it expects to find; a stale table aborts the run.
* Nothing outside the declared sites may differ afterwards.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v3.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v4.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v4.report.json"

# The two cave regions. Unlike v3 these are the *target* of the patch, so the
# rule is inverted: writes MUST fall inside them.
CAVES = {6: [(0x1B464, 0x1B810)], 9: [(0x14F6C, 0x151C0)]}

# The neutered entry points and the immediate-return words that must survive.
# (addr, length) - ARM uses 4-byte `bx lr` + `mov r0,r0`; Thumb uses 2-byte
# `bx lr` + `nop`.
PROTECTED = {
    6: [(0x1B464, 4), (0x1B468, 4), (0x1B688, 4), (0x1B68C, 4)],
    9: [(0x14F6C, 2), (0x14F6E, 2), (0x15110, 2), (0x15112, 2)],
}
# What each protected word must still contain after patching.
PROTECTED_EXPECT = {
    6: {0x1B464: "1eff2fe1", 0x1B688: "1eff2fe1"},
    9: {0x14F6C: "7047", 0x15110: "7047"},
}

# (addr, expected_hex, new_hex, note)
PATCH_SITES: dict[int, list[tuple[int, str, str, str]]] = {
    6: [
        # --- delta zero: sizing job removed -------------------------------
        (0x1B480, "010a30ee", "640a94ed",
         "showRateIt helper: vadd.f32 s0,s0,s2(+4.0) -> vldr s0,[r4,#0x190] (no-op)"),
        (0x1B6A4, "010a30ee", "640a94ed",
         "showTreeWorldPopUp helper: vadd.f32 s0,s0,s2(+3.0) -> vldr s0,[r4,#0x190] (no-op)"),
        # --- retarget: entry -> body (+8) ---------------------------------
        (0x1B4DC, "690000eb", "6b0000eb", "bl 0x1b688 -> 0x1b690 (showOkButtonIn: title1)"),
        (0x1B4F4, "630000eb", "650000eb", "bl 0x1b688 -> 0x1b690 (showOkButtonIn: body1)"),
        (0x1B500, "600000eb", "620000eb", "bl 0x1b688 -> 0x1b690 (showOkButtonIn: body1)"),
        (0x1B50C, "d4ffffeb", "d6ffffeb", "bl 0x1b464 -> 0x1b46c (showOkButtonIn: buttonLabel)"),
        (0x1B5CC, "2d0000eb", "2f0000eb", "bl 0x1b688 -> 0x1b690 (getActorName: title1)"),
        (0x1B5DC, "290000eb", "2b0000eb", "bl 0x1b688 -> 0x1b690 (getActorName: body1)"),
        (0x1B758, "caffffeb", "ccffffeb", "bl 0x1b688 -> 0x1b690 (combinerTapped title1)"),
        (0x1B768, "c6ffffeb", "c8ffffeb", "bl 0x1b688 -> 0x1b690 (combinerTapped body1)"),
    ],
    9: [
        # --- delta zero: sizing job removed -------------------------------
        (0x14F7E, "30ee010a", "94ed640a",
         "showRateIt helper: vadd.f32 s0,s0,s2(+4.0) -> vldr s0,[r4,#0x190] (no-op)"),
        (0x15122, "30ee010a", "94ed640a",
         "showTreeWorldPopUp helper: vadd.f32 s0,s0,s2(+3.0) -> vldr s0,[r4,#0x190] (no-op)"),
        # --- retarget: entry -> body (+4 for Thumb) -----------------------
        (0x14FC6, "00f0a3f8", "00f0a5f8", "bl 0x15110 -> 0x15114 (showOkButtonIn: title1)"),
        (0x14FDA, "00f099f8", "00f09bf8", "bl 0x15110 -> 0x15114 (showOkButtonIn: body1)"),
        (0x14FE4, "00f094f8", "00f096f8", "bl 0x15110 -> 0x15114 (showOkButtonIn: body1)"),
        (0x14FEE, "fff7bdff", "fff7bfff", "bl 0x14f6c -> 0x14f70 (showOkButtonIn: buttonLabel)"),
        (0x15094, "00f03cf8", "00f03ef8", "bl 0x15110 -> 0x15114 (getActorName: title1)"),
        (0x150A0, "00f036f8", "00f038f8", "bl 0x15110 -> 0x15114 (getActorName: body1)"),
        (0x151A0, "fff7b6ff", "fff7b8ff", "bl 0x15110 -> 0x15114 (combinerTapped title1)"),
        (0x151AC, "fff7b0ff", "fff7b2ff", "bl 0x15110 -> 0x15114 (combinerTapped body1)"),
    ],
}


def slice_file_offset(sl: Any, addr: int) -> int:
    off = sl.addr_to_file(addr)
    if off is None:
        raise ValueError(f"address {addr:#x} is not mapped in slice sub{sl.subtype}")
    return off


def check_inside_cave(subtype: int, addr: int, length: int) -> None:
    """v4 writes ONLY inside the caves; anything else is a table bug."""
    for lo, hi in CAVES.get(subtype, []):
        if lo <= addr and addr + length <= hi:
            return
    raise ValueError(f"sub{subtype} site {addr:#x}+{length} is outside every cave")


def check_not_protected(subtype: int, addr: int, length: int) -> None:
    for paddr, plen in PROTECTED.get(subtype, []):
        if addr < paddr + plen and paddr < addr + length:
            raise ValueError(
                f"sub{subtype} site {addr:#x}+{length} would overwrite the "
                f"neutered entry word at {paddr:#x}"
            )


def decode_thumb_bl(addr: int, raw: bytes) -> int:
    f, s2 = struct.unpack_from("<HH", raw, 0)
    sb = (f >> 10) & 1
    j1, j2 = (s2 >> 13) & 1, (s2 >> 11) & 1
    i1, i2 = (~(j1 ^ sb)) & 1, (~(j2 ^ sb)) & 1
    imm = ((sb << 24) | (i1 << 23) | (i2 << 22)
           | ((f & 0x3FF) << 12) | ((s2 & 0x7FF) << 1))
    if imm & (1 << 24):
        imm -= 1 << 25
    return addr + 4 + imm


def decode_arm_bl(addr: int, raw: bytes) -> int:
    w = struct.unpack_from("<I", raw, 0)[0]
    imm = w & 0xFFFFFF
    if imm & 0x800000:
        imm -= 1 << 24
    return addr + 8 + (imm << 2)


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
            check_inside_cave(subtype, addr, len(new))
            check_not_protected(subtype, addr, len(new))
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
                "note": note,
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

    # 1. the neutered entries must still be an immediate return
    entries_ok = []
    for subtype, wants in PROTECTED_EXPECT.items():
        sl_p = slices[subtype]
        base = descriptors[subtype]["offset"]
        for addr, want in wants.items():
            got = patched[base + slice_file_offset(sl_p, addr):
                          base + slice_file_offset(sl_p, addr) + len(want) // 2].hex()
            if got != want:
                raise ValueError(
                    f"sub{subtype} entry {addr:#x} is no longer an immediate "
                    f"return: {got} != {want}"
                )
            entries_ok.append(f"sub{subtype} {addr:#x} {got}")

    # 2. every retargeted branch must decode to the body it claims
    branches = []
    for site in applied:
        if not site["note"].startswith("bl "):
            continue
        subtype = site["subtype"]
        addr = int(site["addr"], 16)
        want = int(site["note"].split("->")[1].split()[0], 16)
        raw = bytes.fromhex(site["new"])
        got = (decode_thumb_bl(addr, raw) if subtype == 9
               else decode_arm_bl(addr, raw))
        if got != want:
            raise ValueError(
                f"sub{subtype} {addr:#x}: branch decodes to {got:#x}, want {want:#x}"
            )
        branches.append(f"sub{subtype} {addr:#x} -> {got:#x}")

    return {"sites_verified": len(applied), "readback": readback,
            "entries_still_neutered": entries_ok,
            "branches_decode_correctly": branches}


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
        "purpose": "repair helper network; remove its +4.0/+3.0 sizing so v3's "
                   "absolute 24/18 is not compounded",
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source),
                  "executable_sha256": sha256(original_exe)},
        "sites": applied,
        "executable_checks": checks,
        "cave_regions": {str(k): [[f"{lo:#x}", f"{hi:#x}"] for lo, hi in v]
                         for k, v in CAVES.items()},
        "protected_entry_words": {str(k): [[f"{a:#x}", n] for a, n in v]
                                  for k, v in PROTECTED.items()},
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

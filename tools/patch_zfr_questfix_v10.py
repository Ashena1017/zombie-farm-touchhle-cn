#!/usr/bin/env python3
"""v10fix - stop GameData's throwaway ZFQuestNotification objects from staying
registered as NSNotification observers, which is what zeroes quest progress.

Root cause (proven by v7diag / v8diag / v9diag)
-----------------------------------------------
`ZFQuestNotification -requirementUpdated:` is registered on EVERY notification
with `object:nil` and rewrites ITS OWN dict entry from ITS OWN `countCurrent`.
v9diag forced that value to 3 and all 20 quests came back as 3 => that normal
branch really is the writer.

`GameData -addUserData:` and `+readUserData:intoGameData:withVersion:` each
build a throwaway notification via `[ZFQuestNotification alloc]
initWithID:questID]` purely to read the plist requirement metadata:

    ARM   0x186d30 bl [ZFQuestNotification alloc]
          0x186d3c bl [.. initWithID:]      ; r0 = notification
          0x186d44 bl [notification autorelease]
          0x186d50 mov r8, r0               ; r8 = notification

`initWithID:` -> `initWithID:loadSprite:` registers requirementUpdated: /
requirementComplete: unconditionally, and (before the loadSprite test) calls
`setIsTouchEnabled:`, so the CCTouchDispatcher keeps the object alive and its
`dealloc` - the only place that calls `removeObserver:` - never runs.  Every
save and every load therefore leaks one permanently-registered observer whose
`countCurrent` is 0, and ONE requirement increment makes all of them rewrite
every quest dict to 0.

The fix
-------
Replace the `autorelease` call with a direct call to
`-[ZFQuestNotification stopListening]`, which enumerates the observer-name ivar
and calls `[[NSNotificationCenter defaultCenter] removeObserver:self name:..]`:

    mov r8, r0        ; save the notification BEFORE the call (r0 is clobbered)
    bl stopListening  ; was: bl objc_msgSend with SEL "autorelease"
    nop               ; was: mov r8, r0

The count still comes from the notification itself, so nothing else changes.
Skipping `autorelease` leaks nothing extra: the touch dispatcher already
retains these objects forever.

Sites (width preserving, both slices):
    sub6 0x186d40 ldr r1,[sp,#0x28] -> mov r8,r0
    sub6 0x186d44 bl objc_msgSend   -> bl 0x16a5ec   (stopListening)
    sub6 0x186d50 mov r8,r0         -> nop
    sub6 0x187dcc ldr r1,[sp,#0x28] -> mov r8,r0
    sub6 0x187dd0 bl objc_msgSend   -> bl 0x16a5ec
    sub6 0x187dd8 mov r8,r0         -> nop
    sub9 0x11f43a ldr r1,[sp,#0x1c] -> mov r8,r0
    sub9 0x11f43c blx objc_msgSend  -> bl 0x10a1dc
    sub9 0x11f440 mov r8,r0         -> nop
    sub9 0x120030 ldr r1,[sp,#0x18] -> mov r5,r0
    sub9 0x120032 blx objc_msgSend  -> bl 0x10a1dc
    sub9 0x120038 mov r5,r0         -> nop
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
OUTPUT_NAME = f"{BASE}.fixed-fonts-v10fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v10fix.report.json"

FORBIDDEN = {6: [(0x1B464, 0x1B810)], 9: [(0x14F6C, 0x151C0)]}

STOP_SUB6 = 0x16A5EC          # -[ZFQuestNotification stopListening]
STOP_SUB9 = 0x10A1DC

# (addr, expected old hex, new hex, note)
FIXED_SITES: dict[int, list[tuple[int, str, str, str]]] = {
    6: [
        (0x186D40, "28109de5", "0080a0e1", "addUserData: keep notification in r8"),
        (0x186D50, "0080a0e1", "0000a0e1", "addUserData: drop dead post-call save"),
        (0x187DCC, "28109de5", "0080a0e1", "readUserData: keep notification in r8"),
        (0x187DD8, "0080a0e1", "0000a0e1", "readUserData: drop dead post-call save"),
    ],
    9: [
        (0x11F43A, "0799", "8046", "addUserData: keep notification in r8"),
        (0x11F440, "8046", "c046", "addUserData: drop dead post-call save"),
        (0x120030, "0699", "0546", "readUserData: keep notification in r5"),
        (0x120038, "0546", "c046", "readUserData: drop dead post-call save"),
    ],
}

# bl sites: addr -> (expected old hex, slice-local target, note)
BL_SITES: dict[int, list[tuple[int, str, int, str]]] = {
    6: [
        (0x186D44, "a53408eb", STOP_SUB6, "addUserData: autorelease -> stopListening"),
        (0x187DD0, "823008eb", STOP_SUB6, "readUserData: autorelease -> stopListening"),
    ],
    9: [
        (0x11F43C, "b0f186ee", STOP_SUB9, "addUserData: autorelease -> stopListening"),
        (0x120032, "b0f18ce8", STOP_SUB9, "readUserData: autorelease -> stopListening"),
    ],
}


def arm_bl(addr: int, target: int) -> bytes:
    off = target - (addr + 8)
    if off % 4:
        raise ValueError(f"ARM bl to {target:#x} from {addr:#x} is not word aligned")
    if not -(1 << 25) <= off < (1 << 25):
        raise ValueError(f"ARM bl out of range: {off}")
    return struct.pack("<I", 0xEB000000 | ((off >> 2) & 0xFFFFFF))


def thumb_bl(addr: int, target: int) -> bytes:
    off = target - (addr + 4)
    if off % 2:
        raise ValueError(f"Thumb bl to {target:#x} from {addr:#x} is not halfword aligned")
    field = off & 0x1FFFFFF
    S = (field >> 24) & 1
    I1 = (field >> 23) & 1
    I2 = (field >> 22) & 1
    imm10 = (field >> 12) & 0x3FF
    imm11 = (field >> 1) & 0x7FF
    J1 = (~(I1 ^ S)) & 1
    J2 = (~(I2 ^ S)) & 1
    hw1 = 0xF000 | (S << 10) | imm10
    # BL (T1): hw2 = `11 J1 1 J2 imm11` -> base 0xD000.  (The original bytes at
    # these sites are `blx` - interworking to the ARM objc_msgSend - whose base
    # is 0xC000; stopListening lives in Thumb code, so BL is what we need.)
    hw2 = 0xD000 | (J1 << 13) | (J2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


def disasm_check(subtype: int, addr: int, raw: bytes, target: int) -> None:
    """Independent check: capstone must read the new bytes as `bl target`."""
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

    if subtype == 6:
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    else:
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    got = list(md.disasm(raw, addr))
    if len(got) != 1:
        raise ValueError(f"sub{subtype} {addr:#x}: {len(got)} instructions decoded")
    ins = got[0]
    if ins.mnemonic != "bl":
        raise ValueError(
            f"sub{subtype} {addr:#x}: decoded `{ins.mnemonic}` (state switch!)")
    if int(ins.op_str.lstrip('#'), 0) != target:
        raise ValueError(
            f"sub{subtype} {addr:#x}: decoded target {ins.op_str}, want {target:#x}")


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


def build_site_list() -> list[tuple[int, int, str, str, str]]:
    """Return (subtype, addr, old_hex, new_hex, note), bl sites first computed."""
    out: list[tuple[int, int, str, str, str]] = []
    for subtype, sites in FIXED_SITES.items():
        for addr, old, new, note in sites:
            out.append((subtype, addr, old, new, note))
    for subtype, sites in BL_SITES.items():
        for addr, old, target, note in sites:
            raw = arm_bl(addr, target) if subtype == 6 else thumb_bl(addr, target)
            disasm_check(subtype, addr, raw, target)
            out.append((subtype, addr, old, raw.hex(), note))
    return out


def apply_sites(original: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    from audit_zfr_ipa import parse_fat

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != set(descriptors) or set(slices) != {6, 9}:
        raise ValueError("unexpected FAT slice set")

    out = bytearray(original)
    applied: list[dict[str, Any]] = []
    for subtype, addr, old_hex, new_hex, note in build_site_list():
        sl = slices[subtype]
        base = descriptors[subtype]["offset"]
        old = bytes.fromhex(old_hex)
        new = bytes.fromhex(new_hex)
        if len(old) != len(new):
            raise ValueError(f"sub{subtype} {addr:#x}: width change forbidden")
        check_forbidden(subtype, addr, len(new))
        absolute = base + slice_file_offset(sl, addr)
        found = bytes(out[absolute:absolute + len(old)])
        if found != old:
            raise ValueError(
                f"sub{subtype} {addr:#x}: expected {old_hex}, found {found.hex()}")
        out[absolute:absolute + len(new)] = new
        applied.append({
            "subtype": subtype, "addr": f"{addr:#08x}", "file_offset": absolute,
            "old": old_hex, "new": new_hex, "note": note,
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
    bl_targets = {(s, a): t for s, v in BL_SITES.items() for a, _o, t, _n in v}
    for site in applied:
        sl = slices[site["subtype"]]
        base = descriptors[site["subtype"]]["offset"]
        addr = int(site["addr"], 16)
        if base + slice_file_offset(sl, addr) != site["file_offset"]:
            raise ValueError(f"sub{site['subtype']} {addr:#x}: offset moved")
        got = patched[site["file_offset"]:
                      site["file_offset"] + len(bytes.fromhex(site["new"]))]
        if got.hex() != site["new"]:
            raise ValueError(f"sub{site['subtype']} {addr:#x}: readback {got.hex()}")
        target = bl_targets.get((site["subtype"], addr))
        if target is not None:
            disasm_check(site["subtype"], addr, got, target)

    for subtype, ranges in FORBIDDEN.items():
        sl_o = next(s for s in parse_fat(original) if s.subtype == subtype)
        sl_p = next(s for s in parse_fat(patched) if s.subtype == subtype)
        for lo, hi in ranges:
            a = slice_file_offset(sl_o, lo)
            b = slice_file_offset(sl_o, hi - 1) + 1
            if sl_o.data[a:b] != sl_p.data[a:b]:
                raise ValueError(
                    f"sub{subtype} helper region {lo:#x}..{hi:#x} was modified")

    return {"sites_verified": len(applied),
            "bl_sites_disasm_verified": sum(
                1 for s in applied if (s["subtype"], int(s["addr"], 16)) in bl_targets),
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
        "kind": "FIX",
        "fixes": "quest progress being zeroed on save (image 3 / tu3)",
        "mechanism": "GameData's throwaway ZFQuestNotification got an autorelease "
                     "where it needed an unregister; replaced with a direct "
                     "stopListening call so its object:nil observers die at once",
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
              f"{site['new']}  {site['note']}")
    print(f"report: {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

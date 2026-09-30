#!/usr/bin/env python3
"""v14fix - make the game's own CJK font branches actually take effect.

The bug v13fix exposed
----------------------
Making the ability name Chinese turned the invasion popup *blank*.  That is not
a coincidence - it is the symptom of a dead language branch:

    +[ZombieFarmAppDelegate getCurrentLanguage]      sub6 0x195004
        return [[[NSUserDefaults standardUserDefaults]
                     objectForKey:@"AppleLanguages"] objectAtIndex:0];

`AppleLanguages` is a *global* default.  It is absent from the game's own
`Library/Preferences/com.playforge.ZombieFarm.ZFR.plist`, so under touchHLE the
call returns nil, and every check of the form

    getCurrentLanguage == "zh-Hant" || == "zh-Hans" || == "ja"

fails.  There are ~30 such checks in the binary (ZFGuiLayer init /
displayMessage: / displayToolTip:, ZFFightGUI, ZFFightMan
getRandomAbilityToUnlock, ZFZombieMenu, ZFAbilityCell, ZFFightAbilityGUI,
OptionsMenu, ZFStorageMenu, ZFMausoleumMenu, ZFZombieCell,
ZFGameCenterDelegate, ...), all injected by the localisation work, and all of
them currently fall to the *bitmap font* side:

    CJK side      : objc_msgSend [CCLabelTTF labelWithString:fontName:fontSize:]
                    font = @"Arial"          -> a real font, renders Chinese
    default side  : objc_msgSend [CCLabelBMFont bitmapFontAtlasWithString:fntFile:]
                    font = @"ABD26.fnt"      -> 122 glyphs, ids 32..282, Latin-1 only

So any Chinese character reaching the default side is silently dropped.  The
pre-v13 popup showed only "ZomBumpkin" because the Chinese around it was
invisible; v13 turned the name Chinese too, so the label became empty.

The fix
-------
Answer the question the callers are really asking.  This IPA is a Chinese build
(`CFBundleDevelopmentRegion = zh_CN`, all UI text resolves to zh-Hans.lproj), so
`getCurrentLanguage` returns the CFString "zh-Hans" - the very constant the
callers compare against.  Single point of change, no cave needed: the method
body is longer than the three instructions the new version needs.

Everything stays width preserving; both slices are patched because it is still
unknown which slice touchHLE executes.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
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
from patch_zfr_questfix_v11 import thumb_movw, thumb_movt, thumb_add_pc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed-fonts-v13fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v14fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v14fix.report.json"

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810),      # codex helper network (live)
        (0x16A5F8, 0x16A70C),    # v12fix stopListening
        (0x16D594, 0x16D5AC)],   # v13fix zfrLocFormat stub
    9: [(0x14F6C, 0x151C0),
        (0x10A1DC, 0x10A29C),
        (0x10C470, 0x10C486)],
}

ZH_HANS_CF = {6: 0x467520, 9: 0x3A34B0}

# (subtype -> (addr, width, sha256 of original, note))
REGIONS: dict[int, list[tuple[int, int, str, str]]] = {
    6: [(0x195004, 0x44,
         "36baa50884b6e0486c91a48ca3addead7a2218cabcf282146fbe6fe64668b9ca",
         "+[ZombieFarmAppDelegate getCurrentLanguage] -> @\"zh-Hans\"")],
    9: [(0x12980C, 0x4E,
         "476a7ec5908fa516a71fad88a12c3ae689a021b76e1bffacebb6f30e4db3561a",
         "+[ZombieFarmAppDelegate getCurrentLanguage] -> @\"zh-Hans\"")],
}


def build_sub6() -> bytes:
    """ARM.  Three instructions, then NOPs, with our own literal in the tail.

        ldr r0, [pc, #0x38]   ; literal at 0x195044
        add r0, pc, r0        ; r0 = (0x195008 + 8) + delta
        bx  lr
    """
    A = 0x195004
    width = 0x44
    lit_at = A + width - 4
    imm = lit_at - (A + 8)
    if not 0 <= imm <= 0xFFF:
        raise ValueError("literal out of ldr range")
    delta = (ZH_HANS_CF[6] - (A + 0x0C)) & 0xFFFFFFFF
    out = b"".join([
        struct.pack("<I", 0xE59F0000 | imm),      # ldr r0, [pc, #imm]
        struct.pack("<I", 0xE08F0000),            # add r0, pc, r0
        struct.pack("<I", 0xE12FFF1E),            # bx  lr
        struct.pack("<I", 0xE1A00000) * ((lit_at - (A + 12)) // 4),
        struct.pack("<I", delta),
    ])
    if len(out) != width:
        raise ValueError("sub6 built %d bytes, need %d" % (len(out), width))
    return out


def build_sub9() -> bytes:
    """Thumb.  movw/movt/add pc/bx lr then NOPs.

    `add r0, pc` computes Align(addr+4, 4) + r0, and the add sits at A+8, so the
    delta must be taken against Align(A+12, 4).
    """
    A = 0x12980C
    width = 0x4E
    add_addr = A + 8
    base = (add_addr + 4) & ~3
    delta = (ZH_HANS_CF[9] - base) & 0xFFFFFFFF
    code = (thumb_movw(0, delta & 0xFFFF) + thumb_movt(0, (delta >> 16) & 0xFFFF)
            + thumb_add_pc(0) + struct.pack("<H", 0x4770))   # bx lr
    nops = struct.pack("<H", 0xBF00) * ((width - len(code)) // 2)
    out = code + nops
    if len(out) != width:
        raise ValueError("sub9 built %d bytes, need %d" % (len(out), width))
    return out


def eval_sub6(raw: bytes, addr: int) -> int:
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    md.detail = True
    ins = list(md.disasm(raw[:12], addr))
    if [i.mnemonic for i in ins] != ["ldr", "add", "bx"]:
        raise ValueError("sub6 shape: %s" % [i.mnemonic for i in ins])
    imm = int(ins[0].op_str.split("#")[1].rstrip("]"), 0)
    lit = addr + 8 + imm
    delta = struct.unpack_from("<I", raw, lit - addr)[0]
    return (delta + addr + 0x0C) & 0xFFFFFFFF


def eval_sub9(raw: bytes, addr: int) -> int:
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    ins = list(md.disasm(raw[:12], addr))
    if [i.mnemonic for i in ins] != ["movw", "movt", "add", "bx"]:
        raise ValueError("sub9 shape: %s" % [i.mnemonic for i in ins])
    lo = int(ins[0].op_str.split("#")[1], 16)
    hi = int(ins[1].op_str.split("#")[1], 16)
    delta = ((hi << 16) | lo) & 0xFFFFFFFF
    return (delta + ((ins[2].address + 4) & ~3)) & 0xFFFFFFFF


def check_bodies() -> list[str]:
    notes = []
    for sub in (6, 9):
        raw = build_sub6() if sub == 6 else build_sub9()
        addr = 0x195004 if sub == 6 else 0x12980C
        got = eval_sub6(raw, addr) if sub == 6 else eval_sub9(raw, addr)
        if got != ZH_HANS_CF[sub]:
            raise ValueError(
                "sub%d body returns %#x, want %#x" % (sub, got, ZH_HANS_CF[sub]))
        notes.append("sub%d body decodes back to CFString %#x (zh-Hans)"
                     % (sub, got))
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    ap.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    ap.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from audit_zfr_ipa import parse_fat

    for line in check_bodies():
        print("  selftest:", line)

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        original = archive.read(EXECUTABLE)

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != {6, 9}:
        raise ValueError("unexpected FAT slice set")

    # the CFString we return must really read "zh-Hans" in both slices
    for sub, addr in ZH_HANS_CF.items():
        sl = slices[sub]
        data_ptr = struct.unpack_from("<I", sl.data, sl.addr_to_file(addr + 8))[0]
        o = sl.addr_to_file(data_ptr)
        s = sl.data[o:sl.data.index(b"\0", o)].decode()
        if s != "zh-Hans":
            raise ValueError("sub%d %#x is %r, not 'zh-Hans'" % (sub, addr, s))
        print("  selftest: sub%d %#x = CFSTR %r" % (sub, addr, s))

    out = bytearray(original)
    applied: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    for subtype, entries in REGIONS.items():
        sl = slices[subtype]
        for addr, width, digest, note in entries:
            for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
                if addr < hi and lo < addr + width:
                    raise ValueError(
                        f"sub{subtype} {addr:#x} overlaps forbidden {lo:#x}")
            a = sl.addr_to_file(addr)
            raw = sl.data[a:a + width]
            got = hashlib.sha256(raw).hexdigest()
            if got != digest:
                raise ValueError(
                    f"sub{subtype} {addr:#x}: original sha {got} != {digest}")
            new = build_sub6() if subtype == 6 else build_sub9()
            absolute = descriptors[subtype]["offset"] + a
            found = bytes(out[absolute:absolute + width])
            if found != raw:
                raise ValueError(f"sub{subtype} {addr:#x}: unexpected current bytes")
            out[absolute:absolute + width] = new
            applied.append({"subtype": subtype, "addr": f"{addr:#08x}",
                            "file_offset": absolute, "len": width,
                            "old_prefix": raw[:16].hex(),
                            "new_prefix": new[:16].hex(), "note": note})
            checks[f"sub{subtype}_{addr:#x}"] = {
                "returns": hex(eval_sub6(new, addr) if subtype == 6
                               else eval_sub9(new, addr))}

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)

    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("patched executable differs outside the intended ranges")

    for s in applied:
        got = patched[s["file_offset"]:s["file_offset"] + s["len"]]
        if got[:16].hex() != s["new_prefix"]:
            raise ValueError(f"readback mismatch at {s['addr']}")

    for subtype, ranges in FORBIDDEN_PRIOR.items():
        sl = slices[subtype]
        for lo, hi in ranges:
            a = sl.addr_to_file(lo)
            b = sl.addr_to_file(hi - 1) + 1
            if original[a:b] != patched[a:b]:
                raise ValueError(f"sub{subtype} forbidden region {lo:#x} modified")

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "root_cause": "+[ZombieFarmAppDelegate getCurrentLanguage] reads NSUserDefaults "
                      "AppleLanguages, which is not set under touchHLE, so it returns nil "
                      "and every injected 'is this a CJK language?' test fails; ~30 font "
                      "branches therefore use CCLabelBMFont with ABD26.fnt (122 Latin "
                      "glyphs) instead of CCLabelTTF with Arial, and all Chinese text on "
                      "those labels is silently dropped",
        "fix": "getCurrentLanguage returns the CFString 'zh-Hans' (this is a zh_CN build), "
               "which is what the callers already compare against",
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "instruction_checks": checks,
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

    print(f"wrote {args.output.name}  ({len(output)} bytes)")
    print(f"  ipa sha256 = {report['output']['sha256']}")
    for s in applied:
        print(f"  sub{s['subtype']} {s['addr']} +{s['len']:>4}  {s['note']}")
    print(f"report: {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

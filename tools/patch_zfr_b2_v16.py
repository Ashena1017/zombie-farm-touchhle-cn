#!/usr/bin/env python3
"""v16fix - repairs the two real defects the v15 live test exposed.

1) THE STUB STACK BUG (my regression, and the reason the tool counter read
   2967885)

   v13fix's sub9 stub ended with `push {r4, lr}` / `blx objc_msgSend` /
   `pop {r4, pc}` so that sp stayed 8-byte aligned across the call.  That extra
   push moves sp down by 8, and `stringWithFormat:` reads its SECOND vararg
   (`%i`) from [sp].  At every affected call site the count had been placed at
   the pre-push sp with `str r0, [sp]`, so the callee read whatever was 8 bytes
   lower - a pointer, printed as 2967885.

   The sub6 stub is stack-correct because ARM can tail-call (`b objc_msgSend`)
   after restoring sp.  Thumb cannot: `objc_msgSend` is ARM code in
   __symbol_stub4, so the call switches state and clobbers lr.

   New sub9 stub (18 bytes), which keeps sp exactly where the original call had
   it:

       push  {r0, r1, r2, lr}
       mov   r0, r3
       bl    zfrLoc
       mov   r3, r0
       pop   {r0, r1, r2, r4}   ; r4 now holds the original return address
       blx   objc_msgSend       ; sp is back to the caller's value
       bx    r4

   r4 is dead at all three sub9 call sites (verified: the next write to r4
   precedes any read).

   This also proves which slice touchHLE executes: only the sub9 stub could
   produce the corrupted counter, so the Thumb slice is the live one.

2) THE MOJIBAKE CFSTRINGS (issue #5, the real root cause)

   The earlier v15 fix repaired Localizable.strings, which is why
   "+200金币(化肥作用)" started rendering.  But the plain "+200eE" comes from a
   hard-coded CFString whose UTF-8 data the codex patch wrote into __const:

       object          text          should be
       0x468b80 / 0x3a4b10   '+%iėĚ'   '+%i金币'
       0x468ee0 / 0x3a4e70   '-%iėĚ'   '-%i金币'
       0x468ef0 / 0x3a4e80   '+%iĘę'   '+%i经验'
       0x469380 / 0x3a5310   '%dėĚ'    '%d金币'

   Those four strings occupy exactly 32 bytes of __const with no slack, so they
   cannot be grown in place.  Instead the corrected UTF-8 goes into free space
   inside the already-dead -[ZFQuestMan removeSeasonalQuests] body, and each
   CFString's `data` and `size` fields are repointed.  `size` is the BYTE
   length (7/7/7/6 -> 9/9/9/8), so both words must be updated.

Everything is width preserving; both slices are patched out of habit even though
sub9 is now known to be the live one.
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
from patch_zfr_ability_v13 import thumb_branch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed-fonts-v15fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v16fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v16fix.report.json"

ZFRLOC_SUB9 = 0x15140
OBJC_MSGSEND_SUB9 = 0x2D014C

# dead -[ZFQuestMan removeSeasonalQuests] body: the stub occupies the first
# 24 (sub6) / 22 (sub9) bytes, the string pool goes right after it
STUB_SUB9 = 0x10C470
STRING_POOL = {6: 0x16D5B0, 9: 0x10C490}
POOL_SIZE = 48

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810),
        (0x16A5F8, 0x16A70C),
        (0x16D594, 0x16D5AC)],   # v13fix stub (v15 edited one word inside)
    9: [(0x14F6C, 0x151C0),
        (0x10A1DC, 0x10A29C),
        (0x10C470, 0x10C486)],   # v13fix/v15 stub  -- rewritten again here
}

STUB_FIX = {
    9: (STUB_SUB9, 22,
        "63c650f9991206642b6295acdaf4ee8e64864740051968a25bc54d855b5ed8fe",
        "zfrLocFormat stub: keep sp at the caller's value (fixes the %i stack arg)"),
}
POOL_SHA = {
    6: (0x16D5B0, 48, "8ea16cb259b50b5cd7bcb31b927b6852e1ac0c8d4d6720fa8a203e356017b9dd"),
    9: (0x10C490, 48, "e3294e9d6c6186edccb91764518258e764300f68e170d33f2ab2b7d17ce7c43a"),
}

# (object, expected data field bytes, expected size field bytes, new string)
CFSTRINGS = {
    6: [(0x468B80, "006e4000", "07000000", "+%i金币"),
        (0x468EE0, "086e4000", "07000000", "-%i金币"),
        (0x468EF0, "106e4000", "07000000", "+%i经验"),
        (0x469380, "186e4000", "06000000", "%d金币")],
    9: [(0x3A4B10, "002e3400", "07000000", "+%i金币"),
        (0x3A4E70, "082e3400", "07000000", "-%i金币"),
        (0x3A4E80, "102e3400", "07000000", "+%i经验"),
        (0x3A5310, "182e3400", "06000000", "%d金币")],
}


def build_sub9_stub() -> bytes:
    A = STUB_SUB9
    out = b"".join([
        struct.pack("<H", 0xB507),                     # push  {r0, r1, r2, lr}
        struct.pack("<H", 0x4618),                     # mov   r0, r3
        thumb_branch(A + 4, ZFRLOC_SUB9, False),       # bl    zfrLoc
        struct.pack("<H", 0x4603),                     # mov   r3, r0
        struct.pack("<H", 0xBC17),                     # pop   {r0, r1, r2, r4}
                                                       #   (0xBD17 would also pop PC:
                                                       #    bit 8 of Thumb POP is PC)
        thumb_branch(A + 12, OBJC_MSGSEND_SUB9, True),  # blx   objc_msgSend (sp == entry sp)
        struct.pack("<H", 0x4720),                     # bx    r4
        struct.pack("<H", 0xBF00),                     # nop
        struct.pack("<H", 0xBF00),                     # nop
    ])
    if len(out) != 22:
        raise ValueError("sub9 stub built %d bytes, want 22" % len(out))
    return out


def build_pool(entries) -> bytes:
    out = b""
    offsets = []
    for _obj, _d, _s, text in entries:
        offsets.append(len(out))
        out += text.encode("utf-8") + b"\0"
    if len(out) > POOL_SIZE:
        raise ValueError("string pool needs %d bytes, have %d" % (len(out), POOL_SIZE))
    return out + b"\0" * (POOL_SIZE - len(out)), offsets


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

    out = bytearray(original)
    applied: list[dict[str, Any]] = []

    def write(subtype, addr, old, new, note, allow_stub=False):
        if len(old) != len(new):
            raise ValueError("width change at %#x" % addr)
        if not allow_stub:
            for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
                if addr < hi and lo < addr + len(new):
                    raise ValueError("sub%d %#x overlaps forbidden %#x" % (subtype, addr, lo))
        absolute = descriptors[subtype]["offset"] + slices[subtype].addr_to_file(addr)
        found = bytes(out[absolute:absolute + len(old)])
        if found != old:
            raise ValueError("sub%d %#x: expected %s, found %s"
                             % (subtype, addr, old.hex(), found.hex()))
        out[absolute:absolute + len(new)] = new
        applied.append({"subtype": subtype, "addr": f"{addr:#08x}",
                        "file_offset": absolute, "len": len(new),
                        "old_prefix": old[:24].hex(), "new_prefix": new[:24].hex(),
                        "note": note})

    # ---- 1. sub9 stub: restore the caller's sp
    addr, width, digest, note = STUB_FIX[9]
    sl = slices[9]
    a = sl.addr_to_file(addr)
    raw = sl.data[a:a + width]
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("sub9 stub sha mismatch")
    write(9, addr, raw, build_sub9_stub(), note, allow_stub=True)

    # ---- 2. corrected UTF-8 into the dead cave, and repoint the CFStrings
    for subtype, entries in CFSTRINGS.items():
        pool_addr = STRING_POOL[subtype]
        _pa, _pn, pool_sha = POOL_SHA[subtype]
        sl = slices[subtype]
        a = sl.addr_to_file(pool_addr)
        raw = sl.data[a:a + POOL_SIZE]
        if hashlib.sha256(raw).hexdigest() != pool_sha:
            raise ValueError("sub%d pool sha mismatch" % subtype)
        pool, offsets = build_pool(entries)
        write(subtype, pool_addr, raw, pool,
              "corrected Chinese UTF-8 for the 4 hard-coded format CFStrings")
        for (obj, want_data, want_size, text), off in zip(entries, offsets):
            new_data = struct.pack("<I", pool_addr + off)
            new_size = struct.pack("<I", len(text.encode("utf-8")))
            write(subtype, obj + 8, bytes.fromhex(want_data), new_data,
                  "CFString %r data -> %#x" % (text, pool_addr + off))
            write(subtype, obj + 12, bytes.fromhex(want_size), new_size,
                  "CFString %r size -> %d" % (text, len(text.encode("utf-8"))))

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)
    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("executable differs outside the intended ranges")

    # readback + structural checks
    final = {s.subtype: s for s in parse_fat(patched)}

    def rd(subtype, addr, n):
        return final[subtype].data[final[subtype].addr_to_file(addr):
                                   final[subtype].addr_to_file(addr) + n]

    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(rd(9, STUB_SUB9, 22), STUB_SUB9)]
    got = [g.strip() for g in got]
    want = ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140", "mov r3, r0",
            "pop {r0, r1, r2, r4}", "blx #0x2d014c", "bx r4", "nop", "nop"]
    if got != want:
        raise ValueError("sub9 stub decoded as %s" % got)

    for subtype, entries in CFSTRINGS.items():
        for obj, _d, _s, text in entries:
            data = struct.unpack("<I", rd(subtype, obj + 8, 4))[0]
            size = struct.unpack("<I", rd(subtype, obj + 12, 4))[0]
            raw = rd(subtype, data, size)
            if raw.decode("utf-8") != text:
                raise ValueError("sub%d %#x -> %r, want %r"
                                 % (subtype, obj, raw, text))
            if size != len(text.encode("utf-8")):
                raise ValueError("sub%d %#x size %d wrong" % (subtype, obj, size))

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "findings": {
            "executed_slice": "sub9 (Thumb) - only its stub could corrupt the %i "
                              "stack argument, which is exactly what the live test showed",
            "stub_bug": "the v13 sub9 stub pushed {r4, lr} before blx objc_msgSend, "
                        "moving sp 8 bytes down so stringWithFormat: read the second "
                        "vararg (the %i count) from the wrong slot",
            "mojibake": "the plain '+200eE' came from hard-coded CFStrings in __const "
                        "(+%iėĚ / -%iėĚ / +%iĘę / %dėĚ) that the codex patch corrupted; "
                        "Localizable.strings was only half the story",
        },
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
        print("  sub%d %s +%d  %s" % (s["subtype"], s["addr"], s["len"], s["note"]))
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

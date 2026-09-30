#!/usr/bin/env python3
"""v17fix - closes issue #1 (the last English string) and the real `+1经验` float.

TWO DEFECTS, ONE ROOT CAUSE EACH
================================

1) "已使用Invasion Voucher!" -- issue #1, third and final attempt
---------------------------------------------------------------

v15 retargeted the sub6 `stringWithFormat:` call and had no effect, because the
sub6 slice is *not* the one touchHLE executes.  v16 proved sub9 is live.  The
sub9 equivalent call site was then reported as "no reference to the '%@ Used!'
CFString anywhere", which was WRONG -- a bug in every scanner in _analysis/:

    Thumb `add rd, pc` (16-bit, T1) bases the PC on **addr + 4, NOT word
    aligned**.  `_dis.py` and _b2_all.py/_v17_cf.py all used Align(addr+4,4),
    so any such instruction sitting at addr % 4 == 2 resolved exactly 2 bytes
    BEFORE its real target -- landing inside the previous CFString struct,
    where the flags check fails and the site is silently dropped.

_v17_pc.py settles it statistically: of 56353 such sites with a known delta,
6629 land exactly on a real __cfstring object with the unaligned base and
**0** land with the aligned base.  (_dis.py is fixed in the same commit.)

With the fix the sub9 site appears -- byte for byte the same shape as sub6:

    0x54140  -[ZFMarketMenu alertWindow:dismissedPositive:]
    ...
    0x54238  r1 = (pool)               -> selref localizedStringForKey:value:table:
    0x54240  r2 = 0x35267e  \
    0x54246  movt r2,#0x35   > delta for the CFString '%@ Used!'
    0x5424e  add  r2, pc    /            -> 0x3a68d0   (KEY)
    0x5424a  r3 = 0x34f0b6  \
    0x54250  movt r3,#0x34   > delta for the cstring  '%@ Used!'
    0x54256  add  r3, pc    /            -> 0x3c...    (VALUE)
    0x54258  str.w sl, [sp]             table = nil
    0x5425c  blx  objc_msgSend          -> r0 = '已使用%@！'
    0x54260  mov  r2, r0                format
    0x5426a  mov  r3, r5                <- the RAW item name ("Invasion Voucher")
    0x54272  blx  objc_msgSend          <- *** retargeted here ***
    0x5428c  blx  objc_msgSend          displayToolTip:duration:

So, exactly as in v15: the template is localised and the `%@` argument is not.
`Localizable.strings` *does* have `"Invasion Voucher" = "立即入侵券";`, so routing
r3 through the zfrLoc helper is enough.

Why not reuse v16's stub at 0x10c470: it parks the return address in **r4**, and
r4 is LIVE here -- the method's common exit at 0x5441c does `strb r1, [r4, r0]`
(r4 == self).  Clobbering it would crash.  Hence a new stub that touches no
callee-saved register at all:

    push.w {r0, r1, r2, lr}      ; save args + return address
    mov    r0, r3                ; localise the %@ argument
    bl     zfrLoc
    mov    r3, r0
    nop                          ; keep the 32-bit ops word aligned
    movw   r12, #0x014c          ; objc_msgSend lives in __symbol_stub4
    movt   r12, #0x002d
    pop.w  {r0, r1, r2, lr}      ; sp == the caller's sp again
    bx     r12                   ; TAIL CALL: bx does not set lr, so
                                 ; objc_msgSend returns straight to 0x54276
                                 ; in Thumb state, and r4..r11 are untouched.

`bx r12` with r12 = 0x2d014c (bit0 == 0) enters ARM state exactly like the
original `blx`; `pop.w` restores lr to 0x54276|1 from the caller's own `bl`.

2) "+1经验" never came back -- there was a SECOND exp format string
------------------------------------------------------------------

v16 repaired `+%i经验` (CFString 0x3a4e80 / 0x468ef0), which is why "+200金币"
started rendering.  But the float the user photographed reads ` +1Ee`, with a
leading space, and comes from a *different* CFString:

    sub6 0x476190 / sub9 0x3b2120

In the UNTOUCHED baseline that object is

    data=0x3d9bc2 (sub6) / 0x315bc2 (sub9)   size=6   text=' +%dxp'

The codex patch tried to localise it, but instead of writing UTF-8 it moved the
`data` pointer into the tail of an unrelated debug cstring it had itself
corrupted (`ZFSaleEndDateDay +%dĘę`) and set size=8.  `Ęę` (U+0118 U+0119) is
what "经验" degenerated into, so the float rendered as " +1Ee" -- and it is NOT
the object v16 fixed, which is why the user still saw nothing.

Fix: 11 bytes of correct UTF-8 (" +%d经验") into each slice's own free dead-code
body, then repoint data + size (byte length 6 -> 10).

Width preserving throughout; every site is asserted against the exact bytes it
must replace, and the whole-file diff is confined to the declared ranges.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v16fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v17fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v17fix.report.json"

# ---------------------------------------------------------------- constants
SITE_VOUCHER = 0x54272          # sub9 -[ZFMarketMenu alertWindow:dismissedPositive:]
SITE_VOUCHER_OLD = "7bf26cef"   # blx #0x2d014c

STUB_ADDR_SUB9 = 0x1138A0       # dead -[ZFFightAbilityGUI fadeOutAllButtons]
STUB_LEN = 26
STUB_SHA_SUB9 = "d099331d2c7e878035e46deab6f97dd80f09c0e27a91c0f2687b69800faf42e1"
STUB_SPAN_SUB9 = 37             # 26 bytes of code + the 11-byte string

POOL_ADDR_SUB6 = 0x177534       # dead -[ZFFightAbilityGUI fadeOutAllButtons]
POOL_SHA_SUB6 = "01f528865ebaac24ec4f8cba4fd0adc859c87f94d9202f052acc5aea53e7757a"
POOL_SPAN_SUB6 = 11

ZFRLOC_SUB9 = 0x15140
OBJC_MSGSEND_SUB9 = 0x2D014C

EXP_TEXT = " +%d经验"

# (object, expected data-field bytes, expected size-field bytes)
EXP_CFSTRINGS = {
    6: (0x476190, "781c3d00", "08000000"),
    9: (0x3B2120, "78dc3000", "08000000"),
}

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810),
        (0x16A5F8, 0x16A70C),
        (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0)],
    9: [(0x14F6C, 0x151C0),
        (0x10A1DC, 0x10A29C),
        (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0)],
}


def build_sub9_stub() -> bytes:
    a = STUB_ADDR_SUB9
    out = b"".join([
        struct.pack("<H", 0xB507),                      # push.w {r0, r1, r2, lr}
        struct.pack("<H", 0x4618),                      # mov    r0, r3
        thumb_branch(a + 4, ZFRLOC_SUB9, False),        # bl     zfrLoc
        struct.pack("<H", 0x4603),                      # mov    r3, r0
        struct.pack("<H", 0xBF00),                      # nop (word-align the rest)
        struct.pack("<HH", 0xF240, 0x1C4C),             # movw   r12, #0x014c
        struct.pack("<HH", 0xF2C0, 0x0C2D),             # movt   r12, #0x002d
        struct.pack("<HH", 0xE8BD, 0x4007),             # pop.w  {r0, r1, r2, lr}
        struct.pack("<H", 0x4760),                      # bx     r12  (tail call)
    ])
    if len(out) != STUB_LEN:
        raise ValueError("sub9 stub built %d bytes, want %d" % (len(out), STUB_LEN))
    return out


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

    # ---- 1. sub9: the tooltip's %@ argument goes through zfrLoc
    sl9 = slices[9]
    o = sl9.addr_to_file(STUB_ADDR_SUB9)
    cave = sl9.data[o:o + STUB_SPAN_SUB9]
    if hashlib.sha256(cave[:STUB_SPAN_SUB9]).hexdigest() != STUB_SHA_SUB9:
        raise ValueError("sub9 cave sha mismatch")
    stub = build_sub9_stub()
    str_off = STUB_ADDR_SUB9 + STUB_LEN
    write(9, STUB_ADDR_SUB9, cave[:STUB_SPAN_SUB9],
          stub + EXP_TEXT.encode("utf-8") + b"\0",
          "new sub9 stub (r4-safe tail call) + the ' +%%d经验' literal", allow_stub=True)
    write(9, SITE_VOUCHER, bytes.fromhex(SITE_VOUCHER_OLD),
          thumb_branch(SITE_VOUCHER, STUB_ADDR_SUB9, False),
          "localise the '%%@' item name before displayToolTip: (issue #1)")

    # ---- 2. the second exp format string
    sl6 = slices[6]
    o6 = sl6.addr_to_file(POOL_ADDR_SUB6)
    cave6 = sl6.data[o6:o6 + POOL_SPAN_SUB6]
    if hashlib.sha256(cave6).hexdigest() != POOL_SHA_SUB6:
        raise ValueError("sub6 cave sha mismatch")

    for subtype, (obj, want_data, want_size) in EXP_CFSTRINGS.items():
        if subtype == 6:
            new_data_addr = POOL_ADDR_SUB6
        else:
            new_data_addr = str_off
        new_size = len(EXP_TEXT.encode("utf-8"))
        write(subtype, obj + 8, bytes.fromhex(want_data),
              struct.pack("<I", new_data_addr),
              "CFString %r data -> %#x" % (EXP_TEXT, new_data_addr))
        write(subtype, obj + 12, bytes.fromhex(want_size),
              struct.pack("<I", new_size),
              "CFString %r size -> %d" % (EXP_TEXT, new_size))

    write(6, POOL_ADDR_SUB6, cave6, EXP_TEXT.encode("utf-8") + b"\0",
          "the ' +%%d经验' literal for sub6", allow_stub=True)

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)
    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("executable differs outside the intended ranges")

    # ---- readback + structural checks -------------------------------------
    final = {s.subtype: s for s in parse_fat(patched)}

    def rd(subtype, addr, n):
        sl = final[subtype]
        f = sl.addr_to_file(addr)
        return sl.data[f:f + n]

    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    got = [("%s %s" % (i.mnemonic, i.op_str)).strip()
           for i in md.disasm(rd(9, STUB_ADDR_SUB9, STUB_LEN), STUB_ADDR_SUB9)]
    want = ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140", "mov r3, r0",
            "nop", "movw ip, #0x14c", "movt ip, #0x2d",
            "pop.w {r0, r1, r2, lr}", "bx ip"]
    if got != want:
        raise ValueError("sub9 stub decoded as %s" % got)

    site = rd(9, SITE_VOUCHER, 4)
    call = [i for i in md.disasm(site, SITE_VOUCHER)]
    if len(call) != 1 or call[0].mnemonic != "bl" or \
            (call[0].operands[0].imm & ~1) != STUB_ADDR_SUB9:
        raise ValueError("voucher site did not retarget: %r" % site.hex())

    for subtype, (obj, _d, _s) in EXP_CFSTRINGS.items():
        data = struct.unpack("<I", rd(subtype, obj + 8, 4))[0]
        size = struct.unpack("<I", rd(subtype, obj + 12, 4))[0]
        raw = rd(subtype, data, size)
        if raw.decode("utf-8") != EXP_TEXT:
            raise ValueError("sub%d %#x -> %r, want %r" % (subtype, obj, raw, EXP_TEXT))
        if size != len(EXP_TEXT.encode("utf-8")):
            raise ValueError("sub%d %#x size %d wrong" % (subtype, obj, size))

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "findings": {
            "scanner_bug": "16-bit Thumb `add rd, pc` uses addr+4 as its base, NOT "
                           "Align(addr+4,4). At addr%4==2 every previous scan "
                           "(_dis.py, _b2_all.py) resolved 2 bytes early and silently "
                           "dropped the site -- this is why the sub9 '%@ Used!' "
                           "reference appeared not to exist.  _v17_pc.py proves it: "
                           "6629 unaligned hits vs 0 aligned hits over 56353 sites.",
            "issue_1_site": "sub9 0x54272 in -[ZFMarketMenu "
                            "alertWindow:dismissedPositive:] feeds the RAW item name "
                            "into stringWithFormat:('已使用%@！').  The template was "
                            "already localised; only the argument was not.",
            "issue_1_r4": "v16's stub cannot be reused: its return address lives in r4 "
                          "and r4 is self here (read at 0x5441c).  The new stub uses a "
                          "bx-r12 tail call and touches no callee-saved register.",
            "exp_string": "the float reading ' +1Ee' is CFString 0x476190/0x3b2120 "
                          "(' +%dxp' in the baseline), NOT the 0x468ef0/0x3a4e80 one "
                          "v16 repaired.  The codex patch had moved its data pointer "
                          "onto the corrupted 'ZFSaleEndDateDay +%dĘę' cstring.",
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

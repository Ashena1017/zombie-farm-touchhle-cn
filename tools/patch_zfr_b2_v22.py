#!/usr/bin/env python3
"""v22fix - batch-2 item #7: the five zombie-detail captions must be black.

WHY THEY ARE WHITE
------------------
`ZFZombieMenu` builds its Chinese labels through a language fork

    [[NSLocale preferredLanguages] objectAtIndex:0]
    if ([lang isEqualToString:@"zh-Hant"]) -> TTF path
    if ([lang isEqualToString:@"zh-Hans"]) -> TTF path
    if ([lang isEqualToString:@"ja"])      -> TTF path
    otherwise                              -> bitmap-font path (ABD26.fnt)

so on a zh-Hans device all five captions are `CCLabelTTF`s created with

    +[CCLabelTTF labelWithString:fontName:'Arial' fontSize:...]

and nothing ever calls `setColor:` on them -> cocos2d's default WHITE.  The
sites are

    0xcf962  -initRightMenu    STATS   (数值)  fontSize 30.0, setScale 0.46
    0xcfaf0  -initRightMenu    ABILITY (能力)  fontSize 30.0, setScale 0.46
    0xd0582  -initStatDisplay  POWER   (力量)  fontSize 26.0, setScale 0.54
    0xd05d2  -initStatDisplay  LIFE    (生命)  fontSize 26.0, setScale 0.54
    0xd061c  -initStatDisplay  SPEED   (速度)  fontSize 26.0, setScale 0.54

(`_analysis/_t7_sweep.py` walks every class and confirms these are the only
CFSTR 'STATS'/'ABILITY'/'POWER'/'LIFE'/'SPEED' label factories in the TTF path.)

THE STUB
--------
Each site's `blx objc_msgSend` (4 bytes) is replaced by `bl 0x1138c8`, a Thumb
stub that performs the original call and then calls `setColor:(0,0,0)`:

    sub   sp, #8                 ; 8-byte aligned frame *below* the caller's
    str.w lr, [sp, #4]           ;   stack argument, so [sp+8] is still the
    ldr.w r12, [sp, #8]          ;   caller's fontSize
    str.w r12, [sp]              ; hand the same stack argument to objc_msgSend
    blx   objc_msgSend           ; r0 = the new label
    str   r0, [sp]
    ldr   r1, [pc, #0x10]        ; @selector(setColor:)
    eors  r2, r2                 ; ccColor3B black
    eors  r3, r3
    blx   objc_msgSend           ; [label setColor:(0,0,0)]
    ldr   r0, [sp]               ; return the label, as the caller expects
    ldr.w lr, [sp, #4]
    add   sp, #8
    bx    lr

Only caller-saved registers (r0-r3, r12) are touched, `sp` and `lr` are
restored, and the stack argument is passed through unchanged -- the caller's
continuation sees exactly what a bare `blx objc_msgSend` would have left.

PLACEMENT
---------
sub9 0x1138c8..0x1138f3, i.e. immediately after the v17 cave
(0x1138a0..0x1138c5).  This address range belongs to an orphan function whose
*prologue* the v17 stub already overwrote, so the body is unreachable by
construction: `_analysis/_v21_refs.py 0x1138a0 0x113a40` finds no branch or
pc-relative reference into it except v17's own retarget at 0x54272.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v21fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v22fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v22fix.report.json"

EXEC_MSGSEND = 0x2D014C          # __symbol_stub4 entry for objc_msgSend (ARM)
SETCOLOR_CSTR = 0x2D16E7         # __objc_methname 'setColor:'
STUB = 0x1138C8                  # sub9 only
STUB_LEN = 40                    # bytes of code, literal follows

# (addr, note)
SITES9: list[tuple[int, str]] = [
    (0x0CF962, "#7 ZFZombieMenu -initRightMenu STATS (数值) label"),
    (0x0CFAF0, "#7 ZFZombieMenu -initRightMenu ABILITY (能力) label"),
    (0x0D0582, "#7 ZFZombieMenu -initStatDisplay POWER (力量) label"),
    (0x0D05D2, "#7 ZFZombieMenu -initStatDisplay LIFE (生命) label"),
    (0x0D061C, "#7 ZFZombieMenu -initStatDisplay SPEED (速度) label"),
]

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5)],
}


# ---------------------------------------------------------------- encoders
def thumb_bl(addr: int, target: int, link: bool = True) -> bytes:
    """BL (PC = addr+4) or BLX (PC = Align(addr+4, 4), target word aligned)."""
    base = (addr + 4) if link else ((addr + 4) & ~3)
    off = target - base
    if off % 2 or off < -0x1000000 or off > 0xFFFFFF:
        raise ValueError("branch offset %#x out of range" % off)
    S = (off >> 24) & 1
    I1 = (off >> 23) & 1
    I2 = (off >> 22) & 1
    imm10 = (off >> 12) & 0x3FF
    imm11 = (off >> 1) & 0x7FF
    J1 = 1 - (I1 ^ S)
    J2 = 1 - (I2 ^ S)
    hw1 = 0xF000 | (S << 10) | imm10
    hw2 = (0xD000 if link else 0xC000) | (J1 << 13) | (J2 << 11) | imm11
    code = struct.pack("<HH", hw1, hw2)

    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    ins = list(md.disasm(code, addr))
    if len(ins) != 1 or ins[0].mnemonic != ("bl" if link else "blx") \
            or (ins[0].operands[0].imm & ~1) != (target & ~1):
        raise ValueError("branch round-trip failed at %#x -> %#x (%s)"
                         % (addr, target, ins[0] if ins else None))
    return code


def build_stub(addr: int) -> bytes:
    """Assemble the setColor: wrapper and check it with capstone."""
    lit_addr = (addr + STUB_LEN + 3) & ~3

    # 16-bit forms: `sub sp,#imm7*4` / `add sp,#imm7*4`
    sub_sp = struct.pack("<H", 0xB080 | (8 >> 2))
    add_sp = struct.pack("<H", 0xB000 | (8 >> 2))
    str_lr = struct.pack("<HH", 0xF8CD, (14 << 12) | 4)      # str.w lr,  [sp, #4]
    ldr_ip = struct.pack("<HH", 0xF8DD, (12 << 12) | 8)      # ldr.w r12, [sp, #8]
    str_ip = struct.pack("<HH", 0xF8CD, (12 << 12) | 0)      # str.w r12, [sp]
    str_r0 = struct.pack("<H", 0x9000)                       # str   r0,  [sp]
    ldr_r0 = struct.pack("<H", 0x9800)                       # ldr   r0,  [sp]
    ldr_lr = struct.pack("<HH", 0xF8DD, (14 << 12) | 4)      # ldr.w lr,  [sp, #4]
    eor2 = struct.pack("<H", 0x4052)                         # eors  r2, r2
    eor3 = struct.pack("<H", 0x405B)                         # eors  r3, r3
    bx_lr = struct.pack("<H", 0x4770)                        # bx    lr

    # addresses of each instruction, walking the layout
    a_sub = addr
    a_strlr = a_sub + 2
    a_ldrip = a_strlr + 4
    a_strip = a_ldrip + 4
    a_blx1 = a_strip + 4
    a_strr0 = a_blx1 + 4
    a_ldr1 = a_strr0 + 2
    a_eor2 = a_ldr1 + 2
    a_eor3 = a_eor2 + 2
    a_blx2 = a_eor3 + 2
    a_ldrr0 = a_blx2 + 4
    a_ldrlr = a_ldrr0 + 2
    a_addsp = a_ldrlr + 4
    a_bxlr = a_addsp + 2
    if a_bxlr + 2 != addr + STUB_LEN:
        raise ValueError("stub layout does not add up")

    pc_base = (a_ldr1 + 4) & ~3                              # LDR literal base
    disp = lit_addr - pc_base
    if disp < 0 or disp % 4 or disp // 4 > 0xFF:
        raise ValueError("literal out of reach (%#x)" % disp)
    ldr_r1 = struct.pack("<H", 0x4900 | (disp // 4))         # ldr r1, [pc, #disp]

    code = b"".join([
        sub_sp, str_lr, ldr_ip, str_ip,
        thumb_bl(a_blx1, EXEC_MSGSEND, link=False),
        str_r0, ldr_r1, eor2, eor3,
        thumb_bl(a_blx2, EXEC_MSGSEND, link=False),
        ldr_r0, ldr_lr, add_sp, bx_lr,
    ])
    if len(code) != STUB_LEN:
        raise ValueError("stub is %d bytes, expected %d" % (len(code), STUB_LEN))

    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(code, addr)]
    want = [
        "sub sp, #8",
        "str.w lr, [sp, #4]",
        "ldr.w ip, [sp, #8]",
        "str.w ip, [sp]",
        "blx #0x2d014c",
        "str r0, [sp]",
        "ldr r1, [pc, #0x%x]" % disp,
        "eors r2, r2",
        "eors r3, r3",
        "blx #0x2d014c",
        "ldr r0, [sp]",
        "ldr.w lr, [sp, #4]",
        "add sp, #8",
        "bx lr",
    ]
    if got != want:
        raise ValueError("stub assembly mismatch:\n  got  %s\n  want %s" % (got, want))
    pad = lit_addr - (addr + STUB_LEN)
    return code + b"\x00" * pad + struct.pack("<I", SETCOLOR_CSTR), lit_addr


# ------------------------------------------------------------------- main
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

    stub, lit_addr = build_stub(STUB)
    blob_len = (lit_addr - STUB) + 4

    # the stub must not overlap anything already claimed
    for lo, hi in FORBIDDEN_PRIOR[9]:
        if STUB < hi and lo < STUB + blob_len:
            raise ValueError("stub %#x overlaps forbidden %#x" % (STUB, lo))
    # ... and it must still live in the same unreferenced orphan function
    if not (0x1138C5 <= STUB and STUB + blob_len <= 0x113940):
        raise ValueError("stub escapes the vetted orphan region")

    out = bytearray(original)
    applied: list[dict[str, Any]] = []

    # 1. the stub itself
    abs_stub = descriptors[9]["offset"] + slices[9].addr_to_file(STUB)
    before = bytes(out[abs_stub:abs_stub + blob_len])
    out[abs_stub:abs_stub + blob_len] = stub
    applied.append({"subtype": 9, "addr": f"{STUB:#08x}", "file_offset": abs_stub,
                    "len": blob_len, "kind": "stub",
                    "old_prefix": before[:16].hex(), "new_prefix": stub[:16].hex(),
                    "literal": f"{SETCOLOR_CSTR:#x}", "literal_at": f"{lit_addr:#08x}",
                    "old_literal_at_16": before[lit_addr - STUB:lit_addr - STUB + 4].hex(),
                    "new_literal": stub[lit_addr - STUB:lit_addr - STUB + 4].hex(),
                    "note": "#7 setColor: wrapper stub"})

    # 2. the five call sites
    for addr, note in SITES9:
        new = thumb_bl(addr, STUB, link=True)
        abs_site = descriptors[9]["offset"] + slices[9].addr_to_file(addr)
        found = bytes(out[abs_site:abs_site + 4])
        if found != bytes.fromhex("00f2f4eb") and found[2:] not in (
                b"\xf2\xeb", b"\xf1\xed"):
            # every site is a blx; decode it and insist on the target
            from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
            md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
            md.detail = True
            ins = list(md.disasm(found, addr))
            if len(ins) != 1 or ins[0].mnemonic != "blx" \
                    or (ins[0].operands[0].imm & ~1) != EXEC_MSGSEND:
                raise ValueError("sub9 %#x: not a blx objc_msgSend (%s)"
                                 % (addr, found.hex()))
        out[abs_site:abs_site + 4] = new
        applied.append({"subtype": 9, "addr": f"{addr:#08x}", "file_offset": abs_site,
                        "len": 4, "kind": "site",
                        "old_prefix": found.hex(), "new_prefix": new.hex(),
                        "branch_to": f"{STUB:#x}", "note": note})

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)
    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("executable differs outside the intended ranges")

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "findings": {
            "#7": "the zh-Hans fork in ZFZombieMenu builds 数值/能力/力量/生命/速度 as "
                  "CCLabelTTF with no setColor:, i.e. cocos2d default white; a shared "
                  "Thumb stub performs the original factory call and then sends "
                  "setColor:(0,0,0) to the new label",
            "placement": "sub9 0x1138c8, inside the orphan function whose prologue the "
                         "v17 stub already replaced; no branch or literal reference "
                         "reaches it (see _analysis/_v21_refs.py)",
        },
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "stub": {"addr": f"{STUB:#x}", "len": blob_len,
                 "selector": f"{SETCOLOR_CSTR:#x}", "literal_at": f"{lit_addr:#x}"},
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
    print("  stub %#x (%d bytes, setColor: %#x via literal @%#x)"
          % (STUB, blob_len, SETCOLOR_CSTR, lit_addr))
    for s in applied[1:]:
        print("  sub9 %s  %s -> %s  %s" % (s["addr"], s["old_prefix"], s["new_prefix"],
                                           s["note"]))
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""v13fix - localise the ability name in the "Unlocked a new %@ ability!" popup.

The bug
-------
`-[ZFFightMan getRandomAbilityToUnlock]` builds the invasion-victory popup.  It
switches on the chosen ability's `tag`, and each case loads one of 23
`__cfstring` constants holding the *internal* actor name:

    Zombie, Girl Zombie, ZomBumpkin, Headless Zombie, Garden Zombie, Zyborg,
    ZomBeauty, ZomBruiser, Kindlehead, ZomBotanist, Zombot, Amazombie,
    ZomBrute, Flamehead, Flower Zombie, ZomGoblin, Robo Zombie, Zombielocks,
    Zombarian, Party Zombie, Zombee, Imp Zombie, zombie

Only the *template* `localizedStringForKey:@"Unlocked a new %@ ability!"` is
localised; the `%@` argument is the raw CFString, so the popup reads
"获得了一项新的ZomBumpkin技能！".

`zh-Hans.lproj/Localizable.strings` already contains all 23 mappings
(`'ZomBumpkin' = '南瓜头僵尸'`, ...); the code simply never asks for them.

The fix
-------
Do not inject any new string.  The binary already ships a nil-safe localisation
helper in the code cave - `zfrLoc(s) = [[NSBundle mainBundle]
localizedStringForKey:s value:s table:nil]`:

    sub6 0x1b6d0 (ARM)      sub9 0x15140 (Thumb)

Both message-building paths end in `objc_msgSend(r0, stringWithFormat:, r2, r3)`
with the raw ability name in `r3`.  Retargeting those two `objc_msgSend` calls
to a tiny stub that runs `r3 = zfrLoc(r3)` first fixes both without moving a
single byte:

    sub6 sites 0xb75ac, 0xb76d4   (arm: `bl 0x393fe0`)   name lives in r5
    sub9 sites 0x86112, 0x86218   (thumb: `blx 0x2d014c`) name lives in r4

Stub placement
--------------
`-[ZFQuestMan removeSeasonalQuests]` is provably dead code in both slices:

  * its selector is absent from `__objc_selrefs` (so no objc_msgSend can reach
    it - checked in both slices),
  * the only occurrence of the string `removeSeasonalQuests` anywhere in the
    slice is the single `__objc_methname` entry (so `NSSelectorFromString` /
    `performSelector:` cannot name it either),
  * no `bl`/`b` in the slice targets its entry point.

Its prologue is therefore a legitimate in-place code cave, exactly like the two
abandoned methods codex already reused at 0x1b464 / 0x14f6c.

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

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed-fonts-v12fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v13fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v13fix.report.json"

# Regions that already hold live injected code.  They must be byte-identical
# before and after, and this patch may never write inside them.
FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810),      # codex helper network (live)
        (0x16A5F8, 0x16A70C)],   # stopListening body + literal pool (v12fix)
    9: [(0x14F6C, 0x151C0),      # codex helper network (live)
        (0x10A1DC, 0x10A29C)],   # stopListening whole method (v12fix)
}

# Regions this patch turns into code.  Any LATER patch must treat them as
# forbidden too; they are published in the report and in the README.
NEW_STUBS: dict[int, list[tuple[int, int]]] = {
    6: [(0x16D594, 0x16D5AC)],   # zfrLocFormat stub (was dead prologue)
    9: [(0x10C470, 0x10C486)],
}

OBJC_MSGSEND_SUB6 = 0x393FE0
OBJC_MSGSEND_SUB9 = 0x2D014C

ZFRLOC_SUB6 = 0x1B6D0               # ARM, r0 -> localised NSString
ZFRLOC_SUB9 = 0x15140               # Thumb, r0 -> localised NSString

STUB_SUB6 = 0x16D594               # inside dead -removeSeasonalQuests
STUB_SUB9 = 0x10C470

# objc_msgSend(stringWithFormat:) sites that consume the raw ability name.
# (addr, len, expected original bytes, name register, note)
RETARGETS: dict[int, list[tuple[int, int, str, int, str]]] = {
    6: [
        (0xB75AC, 4, "8b720beb", 5,
         "CJK branch: bl objc_msgSend -> bl zfrLocFormat (name in r5)"),
        (0xB76D4, 4, "41720beb", 5,
         "default branch: bl objc_msgSend -> bl zfrLocFormat (name in r5)"),
    ],
    9: [
        (0x86112, 4, "4af21ce8", 4,
         "CJK branch: blx objc_msgSend -> bl zfrLocFormat (name in r4)"),
        (0x86218, 4, "49f298ef", 4,
         "default branch: blx objc_msgSend -> bl zfrLocFormat (name in r4)"),
    ],
}

# (lo, hi, sha256 of the original bytes, note)
STUB_REGIONS: dict[int, list[tuple[int, int, str, str]]] = {
    6: [(0x16D594, 0x16D5AC,
         "fd914c6404134b3f2bd56d0246ba3182e628cc717663815350c14bc77ae1f03d",
         "-[ZFQuestMan removeSeasonalQuests] prologue (dead) -> zfrLocFormat stub")],
    9: [(0x10C470, 0x10C486,
         "edf73dd27b670b25c2da1b1955fed2c81fc00d0ab37daa750bff45bbad090d92",
         "-[ZFQuestMan removeSeasonalQuests] prologue (dead) -> zfrLocFormat stub")],
}


# ------------------------------------------------------------------ encoders
def arm_bl(addr: int, target: int) -> bytes:
    off = target - (addr + 8)
    if off % 4:
        raise ValueError(f"ARM bl {addr:#x}->{target:#x} not word aligned")
    if not -(1 << 25) <= off < (1 << 25):
        raise ValueError(f"ARM bl out of range: {off}")
    return struct.pack("<I", 0xEB000000 | ((off >> 2) & 0xFFFFFF))


def arm_b(addr: int, target: int) -> bytes:
    """Unconditional ARM B.  In ARM state a plain B is a tail call: it does not
    touch LR and cannot change instruction set, so `b objc_msgSend` is exactly
    equivalent to the `bl objc_msgSend` it replaces."""
    off = target - (addr + 8)
    if off % 4:
        raise ValueError(f"ARM b {addr:#x}->{target:#x} not word aligned")
    if not -(1 << 25) <= off < (1 << 25):
        raise ValueError(f"ARM b out of range: {off}")
    return struct.pack("<I", 0xEA000000 | ((off >> 2) & 0xFFFFFF))


def thumb_branch(addr: int, target: int, link_exchange: bool) -> bytes:
    """Thumb-2 BL (T1) or BLX (T2).  Copied verbatim from the v11 patcher --
    the two encodings use different bases:

        BLX (T2) base = Align(addr + 4, 4)   (and switches to ARM state)
        BL  (T1) base = addr + 4             (stays in Thumb)
    """
    pc = ((addr + 4) & ~3) if link_exchange else (addr + 4)
    off = target - pc
    if off % 2:
        raise ValueError(f"Thumb branch {addr:#x}->{target:#x} not halfword aligned")
    if link_exchange and off % 4:
        raise ValueError(f"BLX target {target:#x} must be word aligned")
    if not -(1 << 24) <= off < (1 << 24):
        raise ValueError(f"Thumb branch out of range: {off}")
    field = off & 0x1FFFFFF
    S = (field >> 24) & 1
    I1 = (field >> 23) & 1
    I2 = (field >> 22) & 1
    imm10 = (field >> 12) & 0x3FF
    imm11 = (field >> 1) & 0x7FF
    J1 = (~(I1 ^ S)) & 1
    J2 = (~(I2 ^ S)) & 1
    hw1 = 0xF000 | (S << 10) | imm10
    hw2 = (0xC000 if link_exchange else 0xD000) | (J1 << 13) | (J2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


# ---------------------------------------------------------------- the stubs
def build_sub6_stub() -> bytes:
    """24 bytes.  Replaces the (dead) prologue of -removeSeasonalQuests.

    On entry (from the retargeted bl): r0=receiver, r1=SEL stringWithFormat:,
    r2=format, r3=raw ability name, lr=return address.

        push {r0, r1, r2, lr}
        mov  r0, r5                 ; r5 holds the ability name CFString
        bl   zfrLoc                 ; r0 = [[NSBundle mainBundle]
                                    ;       localizedStringForKey:r0 value:r0 table:nil]
        mov  r3, r0                 ; %@ argument is now localised
        pop  {r0, r1, r2, lr}       ; restore receiver / selector / format / lr
        b    objc_msgSend           ; tail call == the original bl
    """
    A = STUB_SUB6
    out = b"".join([
        struct.pack("<I", 0xE92D4007),        # push {r0, r1, r2, lr}
        struct.pack("<I", 0xE1A00005),        # mov  r0, r5
        arm_bl(A + 8, ZFRLOC_SUB6),           # bl   zfrLoc
        struct.pack("<I", 0xE1A03000),        # mov  r3, r0
        struct.pack("<I", 0xE8BD4007),        # pop  {r0, r1, r2, lr}
        arm_b(A + 20, OBJC_MSGSEND_SUB6),     # b    objc_msgSend
    ])
    assert len(out) == 24, hex(len(out))
    return out


def build_sub9_stub() -> bytes:
    """22 bytes.  Same idea as the ARM stub, but Thumb has a trap:

    the 16-bit PUSH can save LR (bit 8 is "M"), but the 16-bit POP cannot
    restore it -- `pop {r0, r1, r2, lr}` encodes as 0xbd07, which capstone (and
    the CPU) read as `pop {r0, r1, r2, pc}`, i.e. it would RETURN from the stub
    and silently skip the format call.  LR must be restored with the 32-bit
    `pop.w {r0, r1, r2, lr}` = 0xe8bd4007.

    `objc_msgSend` is ARM code living in `__symbol_stub4`; the original call
    site used BLX (T2), which switches to ARM state.  A plain `b.w` would NOT
    switch state, so the stub reproduces the original BLX and returns through
    the saved LR instead of tail-calling:

        push   {r0, r1, r2, lr}
        mov    r0, r4               ; r4 holds the ability name CFString
        bl     zfrLoc               ; Thumb -> Thumb, stays in Thumb
        mov    r3, r0
        pop.w  {r0, r1, r2, lr}     ; 32-bit form: LR, not PC
        push   {r4, lr}             ; keep sp 8-byte aligned for the call
        blx    objc_msgSend         ; exactly the instruction we replaced
        pop    {r4, pc}             ; return to our caller
    """
    A = STUB_SUB9
    out = b"".join([
        struct.pack("<H", 0xB507),                      # push {r0, r1, r2, lr}
        struct.pack("<H", 0x4620),                      # mov  r0, r4
        thumb_branch(A + 4, ZFRLOC_SUB9, False),        # bl   zfrLoc
        struct.pack("<H", 0x4603),                      # mov  r3, r0
        struct.pack("<HH", 0xE8BD, 0x4007),             # pop.w {r0, r1, r2, lr}
        struct.pack("<H", 0xB510),                      # push {r4, lr}
        thumb_branch(A + 18, OBJC_MSGSEND_SUB9, True),  # blx  objc_msgSend
        struct.pack("<H", 0xBD10),                      # pop  {r4, pc}
    ])
    assert len(out) == 22, hex(len(out))
    return out


def build_stubs() -> dict[int, list[tuple[int, int, str, bytes, str]]]:
    out: dict[int, list[tuple[int, int, str, bytes, str]]] = {}
    for subtype, entries in STUB_REGIONS.items():
        built = []
        for lo, hi, digest, note in entries:
            new = build_sub6_stub() if subtype == 6 else build_sub9_stub()
            if len(new) != hi - lo:
                raise ValueError(
                    f"sub{subtype} {lo:#x}..{hi:#x}: built {len(new)} bytes, "
                    f"need {hi - lo}")
            built.append((lo, hi, digest, new, note))
        out[subtype] = built
    return out


# ---------------------------------------------------------------- verifier
def disasm(subtype: int, addr: int, raw: bytes) -> list[Any]:
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if subtype == 6 else CS_MODE_THUMB)
    md.detail = True
    return list(md.disasm(raw, addr))


EXPECTED_STUB: dict[int, list[str]] = {
    6: ["push {r0, r1, r2, lr}",
        "mov r0, r5",
        "bl #0x1b6d0",
        "mov r3, r0",
        "pop {r0, r1, r2, lr}",
        "b #0x393fe0"],
    9: ["push {r0, r1, r2, lr}",
        "mov r0, r4",
        "bl #0x15140",
        "mov r3, r0",
        "pop.w {r0, r1, r2, lr}",     # NOT the 16-bit form, which pops PC
        "push {r4, lr}",
        "blx #0x2d014c",
        "pop {r4, pc}"],
}


def check_stub(subtype: int, addr: int, raw: bytes) -> dict[str, Any]:
    """Assert the stub's exact instruction sequence.

    An exact match is used rather than keyword probes because Thumb makes
    `pop {.., lr}` and `pop {.., pc}` differ by one bit: 0xbd07 (16-bit) pops
    PC and would return from the stub without ever calling objc_msgSend, while
    0xe8bd4007 (32-bit) pops LR.  Both disassemble to plausible text, so only a
    literal comparison catches a regression here.
    """
    ins = disasm(subtype, addr, raw)
    got = [f"{i.mnemonic} {i.op_str}".strip() for i in ins]
    want = EXPECTED_STUB[subtype]
    if got != want:
        raise ValueError(
            "sub%d stub sequence mismatch:\n  got  %s\n  want %s"
            % (subtype, got, want))
    msgsend = OBJC_MSGSEND_SUB6 if subtype == 6 else OBJC_MSGSEND_SUB9
    last = ins[-1] if subtype == 6 else ins[-2]
    if int(last.op_str.lstrip('#'), 0) != msgsend:
        raise ValueError(f"sub{subtype} stub: objc_msgSend is not the final call")
    return {"instructions": got}


def check_retarget(subtype: int, addr: int, raw: bytes, stub: int) -> dict[str, Any]:
    ins = disasm(subtype, addr, raw)
    if len(ins) != 1:
        raise ValueError(f"sub{subtype} {addr:#x}: expected 1 instruction")
    i = ins[0]
    if i.mnemonic not in ("bl", "blx"):
        raise ValueError(f"sub{subtype} {addr:#x}: expected bl/blx, got {i.mnemonic}")
    tgt = int(i.op_str.lstrip('#'), 0)
    if tgt != stub:
        raise ValueError(f"sub{subtype} {addr:#x}: target {tgt:#x} != {stub:#x}")
    if subtype == 9 and i.mnemonic != "bl":
        raise ValueError(f"sub{subtype} {addr:#x}: Thumb->Thumb call must be BL (T1)")
    return {"instruction": f"{i.mnemonic} {i.op_str}", "target": hex(tgt)}


def self_test() -> list[str]:
    """Re-encode instructions that really exist in the input binary."""
    notes = []
    arm_b_cases = [(0xB73A0, 0xB74A0, "3e0000ea"),
                   (0xB73AC, 0xB74A0, "3b0000ea"),
                   (0xB7490, 0xB74A0, "020000ea")]
    for addr, tgt, want in arm_b_cases:
        got = arm_b(addr, tgt)
        if got.hex() != want:
            raise ValueError(f"arm_b {addr:#x}->{tgt:#x}: {got.hex()} != {want}")
        notes.append(f"arm_b  {addr:#x}->{tgt:#x} = {got.hex()} (matches original)")

    arm_bl_cases = [(0x1B4D0, 0x1B6D0, "7e0000eb"),
                    (0x1B4E4, 0x1B6D0, "790000eb"),
                    (0x1B4DC, 0x1B690, "6b0000eb")]
    for addr, tgt, want in arm_bl_cases:
        got = arm_bl(addr, tgt)
        if got.hex() != want:
            raise ValueError(f"arm_bl {addr:#x}->{tgt:#x}: {got.hex()} != {want}")
        notes.append(f"arm_bl {addr:#x}->{tgt:#x} = {got.hex()} (matches original)")

    bl_cases = [(0x14FBC, 0x15140, "00f0c0f8"),
                (0x14FCE, 0x15140, "00f0b7f8"),
                (0x151A0, 0x15114, "fff7b8ff")]
    for addr, tgt, want in bl_cases:
        got = thumb_branch(addr, tgt, False)
        if got.hex() != want:
            raise ValueError(f"thumb BL {addr:#x}->{tgt:#x}: {got.hex()} != {want}")
        notes.append(f"thumb BL  {addr:#x}->{tgt:#x} = {got.hex()} (matches original)")

    blx_cases = [(0x86112, 0x2D014C, "4af21ce8"),
                 (0x86218, 0x2D014C, "49f298ef"),
                 (0x120032, 0x2D014C, "b0f18ce8")]
    for addr, tgt, want in blx_cases:
        got = thumb_branch(addr, tgt, True)
        if got.hex() != want:
            raise ValueError(f"thumb BLX {addr:#x}->{tgt:#x}: {got.hex()} != {want}")
        notes.append(f"thumb BLX {addr:#x}->{tgt:#x} = {got.hex()} (matches original)")

    # the new encodings must round-trip through a disassembler as well
    for sub, stub, targets in ((6, STUB_SUB6, (ZFRLOC_SUB6, OBJC_MSGSEND_SUB6)),
                               (9, STUB_SUB9, (ZFRLOC_SUB9, OBJC_MSGSEND_SUB9))):
        raw = build_sub6_stub() if sub == 6 else build_sub9_stub()
        ins = disasm(sub, stub, raw)
        seen = {int(i.op_str.lstrip('#'), 0) for i in ins
                if i.mnemonic in ("bl", "blx", "b")}
        for t in targets:
            if t not in seen:
                raise ValueError(f"sub{sub} stub round-trip lost target {t:#x}")
        notes.append(f"sub{sub} stub round-trips ({len(ins)} instructions)")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    ap.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    ap.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from audit_zfr_ipa import parse_fat

    for line in self_test():
        print("  selftest:", line)

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        original = archive.read(EXECUTABLE)

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != {6, 9}:
        raise ValueError("unexpected FAT slice set")

    out = bytearray(original)
    applied: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    def write(subtype: int, addr: int, old: bytes, new: bytes, note: str) -> None:
        if len(old) != len(new):
            raise ValueError(f"sub{subtype} {addr:#x}: width change forbidden")
        for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
            if addr < hi and lo < addr + len(new):
                raise ValueError(f"sub{subtype} {addr:#x} overlaps forbidden {lo:#x}")
        absolute = descriptors[subtype]["offset"] + slices[subtype].addr_to_file(addr)
        found = bytes(out[absolute:absolute + len(old)])
        if found != old:
            raise ValueError(
                f"sub{subtype} {addr:#x}: expected {old.hex()}, found {found.hex()}")
        out[absolute:absolute + len(new)] = new
        applied.append({"subtype": subtype, "addr": f"{addr:#08x}",
                        "file_offset": absolute, "len": len(new),
                        "old_prefix": old[:24].hex(), "new_prefix": new[:24].hex(),
                        "note": note})

    # 1. carve the two stubs out of dead code
    for subtype, built in build_stubs().items():
        sl = slices[subtype]
        for lo, hi, digest, new, note in built:
            a = sl.addr_to_file(lo)
            b = sl.addr_to_file(hi - 1) + 1
            raw = sl.data[a:b]
            got = hashlib.sha256(raw).hexdigest()
            if got != digest:
                raise ValueError(
                    f"sub{subtype} {lo:#x}..{hi:#x}: original sha {got} != {digest}")
            checks[f"sub{subtype}_stub_{lo:#x}"] = check_stub(subtype, lo, new)
            write(subtype, lo, raw, new, note)

    # 2. retarget the two stringWithFormat: calls per slice
    for subtype, sites in RETARGETS.items():
        stub = STUB_SUB6 if subtype == 6 else STUB_SUB9
        sl = slices[subtype]
        for addr, _n, old_hex, _reg, note in sites:
            old = bytes.fromhex(old_hex)
            raw = (arm_bl(addr, stub) if subtype == 6
                   else thumb_branch(addr, stub, False))
            checks[f"sub{subtype}_retarget_{addr:#x}"] = check_retarget(
                subtype, addr, raw, stub)
            if sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4] != old:
                raise ValueError(f"sub{subtype} {addr:#x}: unexpected original")
            write(subtype, addr, old, raw, note)

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)

    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("patched executable differs outside the intended ranges")

    for s in applied:
        got = patched[s["file_offset"]:s["file_offset"] + s["len"]]
        if got[:24].hex() != s["new_prefix"]:
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
        "root_cause": "getRandomAbilityToUnlock passes the raw internal actor name "
                      "(a __cfstring such as 'ZomBumpkin') as the %@ argument of the "
                      "localised template 'Unlocked a new %@ ability!'; the name is "
                      "never passed through localizedStringForKey:",
        "fix": "retarget both stringWithFormat: objc_msgSend calls to a stub that runs "
               "r3 = zfrLoc(r3) first, where zfrLoc = [[NSBundle mainBundle] "
               "localizedStringForKey:s value:s table:nil] (already present in the "
               "codex code cave)",
        "stub_cave": "the prologue of -[ZFQuestMan removeSeasonalQuests], which is "
                     "dead in both slices (selector absent from __objc_selrefs, no "
                     "branch targets its entry, string occurs only in __objc_methname)",
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "instruction_checks": checks,
        "sites": applied,
        "site_count": len(applied),
        "forbidden_regions": {str(k): [[f"{lo:#x}", f"{hi:#x}"] for lo, hi in v]
                              for k, v in FORBIDDEN_PRIOR.items()},
        "new_stub_regions": {str(k): [[f"{lo:#x}", f"{hi:#x}"] for lo, hi in v]
                             for k, v in NEW_STUBS.items()},
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

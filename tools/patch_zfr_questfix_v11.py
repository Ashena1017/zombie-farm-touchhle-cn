#!/usr/bin/env python3
"""v11fix - make `-[ZFQuestNotification stopListening]` actually unregister the
notification itself, which is what stops quest progress being zeroed.

Why v10fix did not work
-----------------------
v10fix retargeted the throwaway's `autorelease` call to `stopListening`, on the
assumption that stopListening removes the observers that corrupt the save.  It
does not.  There are two independent registrations on this class:

    startListening      registers each ZFQuestRequirement OBJECT for
                        name=[requirement notificationID]
                        selector=incrementCount:

    initWithID:loadSprite:  (0x169d8c..0x169dcc) registers the NOTIFICATION
                        itself, object:nil, for
                        selector=requirementUpdated: / requirementComplete:

`stopListening` only undoes the first (it enumerates ivar +0x128 = requirements
and calls [center removeObserver:<requirement>]).  The throwaway never called
`startListening`, so calling `stopListening` on it was a no-op, and the
object:nil registration survived - so every requirement update still made the
throwaway rewrite its own quest dict from its own countCurrent, which is 0.

The only code that undoes the second registration is `dealloc`:

    0x169f64  [NSNotificationCenter defaultCenter]
    0x169f78  [center removeObserver:self]

and `dealloc` never runs, because the throwaway is never released.

The fix
-------
Rewrite the body of `-[ZFQuestNotification stopListening]` in both slices so it
performs

    [[NSNotificationCenter defaultCenter] removeObserver:self];

`removeObserver:self` (single argument) drops every registration of the
receiver, i.e. both requirementUpdated: and requirementComplete:.  The existing
v10 factory patch already calls `stopListening` on every throwaway, so this is
sufficient.  Semantically this is what "stop listening" should have meant.

Cost: the per-requirement observers registered by startListening are no longer
removed one by one when a live notification is cleaned up.  That is a small
leak, not a correctness problem - the notification itself is unregistered, so
nothing writes the dict from it any more.

Everything is width preserving; both slices are patched because it is still
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
INPUT_NAME = f"{BASE}.fixed-fonts-v6.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v12fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v12fix.report.json"

FORBIDDEN = {6: [(0x1B464, 0x1B810)], 9: [(0x14F6C, 0x151C0)]}

OBJC_MSGSEND_SUB6 = 0x393FE0
OBJC_MSGSEND_SUB9 = 0x2D014C

NC_CLASSREF_SUB6 = 0x45DF24        # __objc_classrefs -> NSNotificationCenter
SEL_DEFAULTCENTER_SUB6 = 0x457D44
SEL_REMOVEOBSERVER_SUB6 = 0x457DC4

NC_CLASSREF_SUB9 = 0x399EAC
SEL_DEFAULTCENTER_SUB9 = 0x393CCC
SEL_REMOVEOBSERVER_SUB9 = 0x393D4C

STOP_SUB6 = 0x16A5EC               # -[ZFQuestNotification stopListening]
STOP_SUB9 = 0x10A1DC

# ---------------------------------------------------------------- v10 sites
# NOTE on the two `readUserData:` entries whose new bytes end in a `mov r0, ..`:
# the original instruction was `autorelease`, which RETURNS SELF, so r0 carried
# the notification into the very next objc_msgSend.  Replacing it with
# stopListening destroys r0, and the following call then used the stale
# NSNotificationCenter instance as its receiver (touchHLE panic: "Object
# 0x3cc3e40 (class NSNotificationCenter) does not respond to selector
# requirements!").  Those two sites therefore restore r0 from the register that
# now holds the notification.  The two `addUserData:` sites do not need this:
# their r0 is overwritten before it is next read.
FIXED_SITES: dict[int, list[tuple[int, str, str, str]]] = {
    6: [
        (0x186D40, "28109de5", "0080a0e1", "addUserData: keep notification in r8"),
        (0x186D50, "0080a0e1", "0000a0e1", "addUserData: r0 rewritten before next read"),
        (0x187DCC, "28109de5", "0080a0e1", "readUserData: keep notification in r8"),
        (0x187DD8, "0080a0e1", "0800a0e1", "readUserData: r0 = r8 (receiver of next call)"),
    ],
    9: [
        (0x11F43A, "0799", "8046", "addUserData: keep notification in r8"),
        (0x11F440, "8046", "c046", "addUserData: r0 rewritten before next read"),
        (0x120030, "0699", "0546", "readUserData: keep notification in r5"),
        (0x120038, "0546", "2846", "readUserData: r0 = r5 (receiver of next call)"),
    ],
}

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

# ------------------------------------------------------- full-range rewrites
# (lo, hi, sha256 of the original bytes, is_code, note)
REWRITES: dict[int, list[tuple[int, int, str, bool, str]]] = {
    6: [
        (0x16A5F8, 0x16A700,
         "6fb506ee0b87ab01b0add3818e5b54f953f8a4cbfd23ac0051936961a747ab96", True,
         "stopListening body -> [[NSNotificationCenter defaultCenter] removeObserver:self]"),
        (0x16A700, 0x16A70C,
         "4b4fb3ea29f03d701040e00e8f6ae22e5e850c434813194be0e51451cb254a28", False,
         "stopListening literal pool: 3 deltas retargeted"),
    ],
    9: [
        (0x10A1DC, 0x10A29C,
         "2d16e2b0ab7896ded4d50ce45137c57835a6fa53367c47977b19174b6a44ccdb", True,
         "stopListening whole method -> removeObserver:self"),
    ],
}


# ------------------------------------------------------------------ encoders
def arm_bl(addr: int, target: int) -> bytes:
    off = target - (addr + 8)
    if off % 4:
        raise ValueError(f"ARM bl {addr:#x}->{target:#x} not word aligned")
    if not -(1 << 25) <= off < (1 << 25):
        raise ValueError(f"ARM bl out of range: {off}")
    return struct.pack("<I", 0xEB000000 | ((off >> 2) & 0xFFFFFF))


def thumb_branch(addr: int, target: int, link_exchange: bool) -> bytes:
    """Thumb-2 BL (T1, hw2 base 0xD000) or BLX (T2, hw2 base 0xC000).

    The two have DIFFERENT bases, established empirically against this binary:

      BLX (T2)  base = Align(addr + 4, 4)   - the original BLX at 0x120032
                (addr % 4 == 2) to objc_msgSend 0x2d014c is encoded b0f18ce8,
                field 0x1b0118 == 0x2d014c - 0x120034.

      BL  (T1)  base = addr + 4             - of the 340 BL(T1) instructions
                sitting at addr % 4 == 2, the hot targets decode to 0x280dd8 and
                0x26cbbc, both of which are `sub sp, #0x20` function entries
                immediately preceded by a `pop {r7, pc}` / padding; the aligned
                base instead yields 0x280dd6 (that very `pop`) and 0x26cbba
                (padding).
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


def thumb_movw(reg: int, imm16: int) -> bytes:
    i = (imm16 >> 11) & 1
    imm4 = (imm16 >> 12) & 0xF
    imm3 = (imm16 >> 8) & 7
    imm8 = imm16 & 0xFF
    return struct.pack("<HH", 0xF240 | (i << 10) | imm4,
                       (imm3 << 12) | (reg << 8) | imm8)


def thumb_movt(reg: int, imm16: int) -> bytes:
    i = (imm16 >> 11) & 1
    imm4 = (imm16 >> 12) & 0xF
    imm3 = (imm16 >> 8) & 7
    imm8 = imm16 & 0xFF
    return struct.pack("<HH", 0xF2C0 | (i << 10) | imm4,
                       (imm3 << 12) | (reg << 8) | imm8)


def thumb_add_pc(reg: int) -> bytes:
    return struct.pack("<H", 0x4478 | ((reg >> 3) << 7) | (reg & 7))


def thumb_ldr_self(reg: int) -> bytes:
    return struct.pack("<H", 0x6800 | (reg << 3) | reg)


def thumb_mov(rd: int, rm: int) -> bytes:
    return struct.pack("<H", 0x4600 | ((rd >> 3) << 7) | (rm << 3) | (rd & 7))


def thumb_materialize(addr: int, reg: int, target: int) -> bytes:
    """movw/movt + add reg,pc + ldr reg,[reg]  -> reg = *(void**)target."""
    if addr % 4:
        raise ValueError(f"materialize site {addr:#x} must be 4-aligned")
    value = (target - ((addr + 12) & ~3)) & 0xFFFFFFFF
    return (thumb_movw(reg, value & 0xFFFF) + thumb_movt(reg, (value >> 16) & 0xFFFF)
            + thumb_add_pc(reg) + thumb_ldr_self(reg))


EMITTERS: dict[int, Any] = {}


def build_sub6_body() -> bytes:
    A = 0x16A5F8
    out = b"".join([
        struct.pack("<I", 0xE1A04000),            # 0x16a5f8 mov r4, r0
        struct.pack("<I", 0xE59F00FC),            # 0x16a5fc ldr r0, [pc, #0xfc] -> 0x16a700
        struct.pack("<I", 0xE08F0000),            # 0x16a600 add r0, pc, r0
        struct.pack("<I", 0xE5900000),            # 0x16a604 ldr r0, [r0] = NC class
        struct.pack("<I", 0xE59F10F4),            # 0x16a608 ldr r1, [pc, #0xf4] -> 0x16a704
        struct.pack("<I", 0xE08F1001),            # 0x16a60c add r1, pc, r1
        struct.pack("<I", 0xE5911000),            # 0x16a610 ldr r1, [r1] = SEL defaultCenter
        arm_bl(0x16A614, OBJC_MSGSEND_SUB6),      # 0x16a614 bl objc_msgSend
        struct.pack("<I", 0xE59F10E8),            # 0x16a618 ldr r1, [pc, #0xe8] -> 0x16a708
        struct.pack("<I", 0xE08F1001),            # 0x16a61c add r1, pc, r1
        struct.pack("<I", 0xE5911000),            # 0x16a620 ldr r1, [r1] = SEL removeObserver:
        struct.pack("<I", 0xE1A02004),            # 0x16a624 mov r2, r4   (observer = self)
        arm_bl(0x16A628, OBJC_MSGSEND_SUB6),      # 0x16a628 bl objc_msgSend
        struct.pack("<I", 0xE247D018),            # 0x16a62c sub sp, r7, #0x18
        struct.pack("<I", 0xE8BD0D00),            # 0x16a630 pop {r8, sl, fp}
        struct.pack("<I", 0xE8BD80F0),            # 0x16a634 pop {r4, r5, r6, r7, pc}
    ])
    assert len(out) == 0x16A638 - A, hex(len(out))
    nops = struct.pack("<I", 0xE1A00000) * ((0x16A700 - 0x16A638) // 4)
    return out + nops


def build_sub6_pool() -> bytes:
    def delta(consume_addr: int, target: int) -> int:
        return target - (consume_addr + 8)

    return b"".join([
        struct.pack("<I", delta(0x16A600, NC_CLASSREF_SUB6)),        # @0x16a700
        struct.pack("<I", delta(0x16A60C, SEL_DEFAULTCENTER_SUB6)),  # @0x16a704
        struct.pack("<I", delta(0x16A61C, SEL_REMOVEOBSERVER_SUB6)),  # @0x16a708
    ])


def build_sub9_method() -> bytes:
    A = 0x10A1DC
    out = b"".join([
        struct.pack("<H", 0xB510),                                  # 0x10a1dc push {r4, lr}
        thumb_mov(4, 0),                                            # 0x10a1de mov r4, r0
        thumb_materialize(0x10A1E0, 0, NC_CLASSREF_SUB9),           # 0x10a1e0..0x10a1eb
        thumb_materialize(0x10A1EC, 1, SEL_DEFAULTCENTER_SUB9),      # 0x10a1ec..0x10a1f7
        thumb_branch(0x10A1F8, OBJC_MSGSEND_SUB9, True),            # 0x10a1f8 blx objc_msgSend
        thumb_materialize(0x10A1FC, 1, SEL_REMOVEOBSERVER_SUB9),     # 0x10a1fc..0x10a207
        thumb_mov(2, 4),                                            # 0x10a208 mov r2, r4
        struct.pack("<H", 0xBF00),                                  # 0x10a20a nop (align)
        thumb_branch(0x10A20C, OBJC_MSGSEND_SUB9, True),            # 0x10a20c blx objc_msgSend
        struct.pack("<H", 0xBD10),                                  # 0x10a210 pop {r4, pc}
    ])
    assert len(out) == 0x10A212 - A, hex(len(out))
    nops = struct.pack("<H", 0xBF00) * ((0x10A29C - 0x10A212) // 2)
    return out + nops


def build_rewrites() -> dict[int, list[tuple[int, int, str, bytes, str, bool]]]:
    out: dict[int, list[tuple[int, int, str, bytes, str, bool]]] = {}
    for subtype, entries in REWRITES.items():
        built = []
        for lo, hi, digest, is_code, note in entries:
            if subtype == 6 and lo == 0x16A5F8:
                new = build_sub6_body()
            elif subtype == 6 and lo == 0x16A700:
                new = build_sub6_pool()
            elif subtype == 9:
                new = build_sub9_method()
            else:
                raise ValueError(f"no builder for sub{subtype} {lo:#x}")
            if len(new) != hi - lo:
                raise ValueError(
                    f"sub{subtype} {lo:#x}..{hi:#x}: built {len(new)} bytes, "
                    f"need {hi - lo}")
            built.append((lo, hi, digest, new, note, is_code))
        out[subtype] = built
    return out


# ------------------------------------------------------------------ verifier
def disasm_scan(subtype: int, addr: int, raw: bytes) -> list[Any]:
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if subtype == 6 else CS_MODE_THUMB)
    return list(md.disasm(raw, addr))


def check_rewrite(subtype: int, lo: int, raw: bytes) -> dict[str, Any]:
    ins = disasm_scan(subtype, lo, raw)
    calls = []
    for i in ins:
        if i.mnemonic in ("bl", "blx"):
            calls.append((i.address, i.mnemonic, int(i.op_str.lstrip('#'), 0)))
    want = OBJC_MSGSEND_SUB6 if subtype == 6 else OBJC_MSGSEND_SUB9
    for _a, mn, tgt in calls:
        if tgt != want:
            raise ValueError(f"sub{subtype}: unexpected branch target {tgt:#x}")
        if subtype == 9 and mn != "blx":
            raise ValueError("sub9 objc_msgSend must be reached with blx")
        if subtype == 6 and mn != "bl":
            raise ValueError("sub6 objc_msgSend must be reached with bl")
    if len(calls) != 2:
        raise ValueError(f"sub{subtype} {lo:#x}: expected 2 calls, got {len(calls)}")

    # the removeObserver call must be preceded by moving the saved receiver into r2
    text = " ; ".join(f"{i.mnemonic} {i.op_str}" for i in ins)
    for needle in ("mov r4, r0", "mov r2, r4"):
        if needle not in text:
            raise ValueError(f"sub{subtype} {lo:#x}: missing `{needle}`")
    if "ldr r0, [r0]" not in text or "ldr r1, [r1]" not in text:
        raise ValueError(f"sub{subtype} {lo:#x}: selector/class loads missing")
    return {"instructions": len(ins), "calls": [[hex(a), m, hex(t)] for a, m, t in calls]}


def eval_materialize(addr: int, raw: bytes) -> int:
    """Decode movw/movt/add pc/ldr and return the address finally loaded from."""
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    ins = list(md.disasm(raw, addr))
    if [i.mnemonic for i in ins] != ["movw", "movt", "add", "ldr"]:
        raise ValueError("materialize shape: " + str([i.mnemonic for i in ins]))
    lo = int(ins[0].op_str.split('#')[1], 16)
    hi = int(ins[1].op_str.split('#')[1], 16)
    value = (hi << 16) | lo
    add_addr = ins[2].address
    return (value + ((add_addr + 4) & ~3)) & 0xFFFFFFFF


def self_test() -> list[str]:
    """Reproduce known-good encodings taken from the untouched binary."""
    notes = []
    arm_cases = [
        (0x186D44, 0x393FE0, "a53408eb"),
        (0x187DD0, 0x393FE0, "823008eb"),
        (0x16A614, 0x393FE0, None),
    ]
    for addr, target, want in arm_cases:
        got = arm_bl(addr, target)
        if want is not None and got.hex() != want:
            raise ValueError(f"arm_bl {addr:#x}->{target:#x}: {got.hex()} != {want}")
        notes.append(f"arm_bl {addr:#x}->{target:#x} = {got.hex()}"
                     + (" (matches original)" if want else ""))

    blx_cases = [
        (0x11F43C, 0x2D014C, "b0f186ee"),
        (0x120032, 0x2D014C, "b0f18ce8"),
        (0x11F46A, 0x2D014C, "b0f170ee"),
        (0x11F476, 0x2D014C, "b0f16aee"),
        (0x10A21C, 0x2D014C, "c5f196ef"),
        (0x10A268, 0x2D014C, "c5f170ef"),
        (0x1200EA, 0x2D014C, "b0f130e8"),
    ]
    for addr, target, want in blx_cases:
        got = thumb_branch(addr, target, True)
        if got.hex() != want:
            raise ValueError(
                f"thumb_branch(BLX) {addr:#x}->{target:#x}: {got.hex()} != {want}")
        notes.append(f"blx {addr:#x}->{target:#x} = {got.hex()} (matches original)")

    bl_cases = [
        # BL (T1) base = addr + 4 ; the first two are also what v10fix encoded
        (0x120032, 0x10A1DC, "eaf7d3f8"),
        (0x11F43C, 0x10A1DC, "eaf7cefe"),
    ]
    for addr, target, want in bl_cases:
        got = thumb_branch(addr, target, False)
        if got.hex() != want:
            raise ValueError(
                f"thumb_branch(BL) {addr:#x}->{target:#x}: {got.hex()} != {want}")
        notes.append(f"bl  {addr:#x}->{target:#x} = {got.hex()}")

    mat_cases = [
        (0x10A1E0, 0, NC_CLASSREF_SUB9),
        (0x10A1EC, 1, SEL_DEFAULTCENTER_SUB9),
        (0x10A1FC, 1, SEL_REMOVEOBSERVER_SUB9),
    ]
    for addr, reg, target in mat_cases:
        raw = thumb_materialize(addr, reg, target)
        got = eval_materialize(addr, raw)
        if got != target:
            raise ValueError(
                f"materialize {addr:#x} r{reg} -> {got:#x}, want {target:#x}")
        notes.append(f"materialize {addr:#x} r{reg} -> {target:#x} ok")

    for addr, target, want_hex in (
            (0x186D44, STOP_SUB6, None), (0x187DD0, STOP_SUB6, None)):
        got = arm_bl(addr, target)
        ins = disasm_scan(6, addr, got)
        if len(ins) != 1 or ins[0].mnemonic != "bl" or \
                int(ins[0].op_str.lstrip('#'), 0) != target:
            raise ValueError(f"arm_bl {addr:#x}->{target:#x} did not round-trip")
        notes.append(f"arm_bl {addr:#x}->{target:#x} = {got.hex()} round-trips")
    return notes


def verify_r0_handoff(patched: bytes, slices: dict[int, Any],
                      descriptors: dict[int, Any]) -> dict[str, Any]:
    """The instruction after each factory patch must still see the notification.

    `autorelease` returned self, so r0 used to carry the notification straight
    into the next objc_msgSend.  Two call sites rely on that; the other two
    overwrite r0 first.  Check both shapes explicitly so a future edit cannot
    silently reintroduce the v11fix crash.
    """
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

    # addr -> (expected first instruction, whether the following call uses r0)
    cases = {
        (6, 0x187DD8): ("mov r0, r8", True),
        (9, 0x120038): ("mov r0, r5", True),
        (6, 0x186D50): ("mov r0, r0", False),
        (9, 0x11F440): ("mov r8, r8", False),
    }
    out: dict[str, Any] = {}
    for (sub, addr), (want, uses_r0) in cases.items():
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
        off = descriptors[sub]["offset"] + slices[sub].addr_to_file(addr)
        ins = list(md.disasm(patched[off:off + 24], addr))
        got = "%s %s" % (ins[0].mnemonic, ins[0].op_str.strip())
        if got != want:
            raise ValueError(f"sub{sub} {addr:#x}: expected `{want}`, found `{got}`")
        if uses_r0:
            nxt = [i for i in ins[1:4] if i.mnemonic in ("bl", "blx")]
            if not nxt:
                raise ValueError(
                    f"sub{sub} {addr:#x}: no call follows, r0 handoff unverified")
        out[f"sub{sub}_{addr:#x}"] = {"instruction": got, "restores_r0": uses_r0}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    ap.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    ap.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from audit_zfr_ipa import parse_fat

    selftest_notes = self_test()
    for line in selftest_notes:
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

    def write(subtype: int, addr: int, old: bytes, new: bytes, note: str) -> None:
        if len(old) != len(new):
            raise ValueError(f"sub{subtype} {addr:#x}: width change forbidden")
        for lo, hi in FORBIDDEN.get(subtype, []):
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
                        "old_prefix": old[:16].hex(), "new_prefix": new[:16].hex(),
                        "note": note})

    # 1. stopListening rewrites
    checks: dict[str, Any] = {}
    for subtype, built in build_rewrites().items():
        sl = slices[subtype]
        for lo, hi, digest, new, note, is_code in built:
            a = sl.addr_to_file(lo)
            b = sl.addr_to_file(hi - 1) + 1
            raw = sl.data[a:b]
            got = hashlib.sha256(raw).hexdigest()
            if got != digest:
                raise ValueError(
                    f"sub{subtype} {lo:#x}..{hi:#x}: original sha {got} != {digest}")
            if is_code:
                checks[f"sub{subtype}_{lo:#x}"] = check_rewrite(subtype, lo, new)
            write(subtype, lo, raw, new, note)

    # 2. v10 factory sites
    for subtype, sites in FIXED_SITES.items():
        sl = slices[subtype]
        for addr, old_hex, new_hex, note in sites:
            write(subtype, addr, bytes.fromhex(old_hex), bytes.fromhex(new_hex), note)
    for subtype, sites in BL_SITES.items():
        for addr, old_hex, target, note in sites:
            raw = (arm_bl(addr, target) if subtype == 6
                   else thumb_branch(addr, target, False))
            ins = disasm_scan(subtype, addr, raw)
            if len(ins) != 1 or ins[0].mnemonic != "bl":
                raise ValueError(f"sub{subtype} {addr:#x}: bad bl encoding")
            if int(ins[0].op_str.lstrip('#'), 0) != target:
                raise ValueError(f"sub{subtype} {addr:#x}: bl target mismatch")
            write(subtype, addr, bytes.fromhex(old_hex), raw, note)

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)

    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("patched executable differs outside the intended ranges")

    # independent readback
    for s in applied:
        got = patched[s["file_offset"]:s["file_offset"] + s["len"]]
        if got[:16].hex() != s["new_prefix"]:
            raise ValueError(f"readback mismatch at {s['addr']}")

    for subtype, ranges in FORBIDDEN.items():
        sl = slices[subtype]
        for lo, hi in ranges:
            a = sl.addr_to_file(lo)
            b = sl.addr_to_file(hi - 1) + 1
            if original[a:b] != patched[a:b]:
                raise ValueError(f"sub{subtype} forbidden region {lo:#x} modified")

    handoff = verify_r0_handoff(patched, slices, descriptors)

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "supersedes": "fixed-fonts-v10fix.ipa (which patched the wrong method)",
        "root_cause": "initWithID:loadSprite: registers the notification itself for "
                      "requirementUpdated:/requirementComplete: with object:nil; the "
                      "throwaway created by GameData is never deallocated, so "
                      "dealloc's [center removeObserver:self] never runs and the "
                      "throwaway keeps rewriting every quest dict from its own "
                      "countCurrent == 0",
        "fix": "stopListening now performs [[NSNotificationCenter defaultCenter] "
               "removeObserver:self], and the v10 factory patch calls it on every "
               "throwaway right after initWithID:",
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "rewrite_checks": checks,
        "r0_handoff_checks": handoff,
        "sites": applied,
        "site_count": len(applied),
        "forbidden_regions": {str(k): [[f"{lo:#x}", f"{hi:#x}"] for lo, hi in v]
                              for k, v in FORBIDDEN.items()},
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

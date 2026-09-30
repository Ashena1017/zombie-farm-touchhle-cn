#!/usr/bin/env python3
"""v28fix - repair the v11fix regression properly, inside the game binary.

Background
----------
v11fix rewrote the whole body of `-[ZFQuestNotification stopListening]` so it
did nothing but

    [[NSNotificationCenter defaultCenter] removeObserver:self];

That was necessary to stop quest progress being zeroed (the notification itself
stayed registered for `requirementUpdated:` / `requirementComplete:` with
`object:nil`, and every throwaway instance rewrote the quest dict from its own
`countCurrent == 0`).

But v11fix also **deleted** the original per-requirement unregistration loop.
`-startListening` registers every `ZFQuestRequirement` object as an observer
for selector `incrementCount:`; with the loop gone those registrations were
never removed.  `NSNotificationCenter` stores observers as raw, unretained
pointers, so as soon as a `ZFQuestRequirement` was released its table entry
became a dangling pointer.  The next post of that notification name then sent
`incrementCount:` to whatever object had reused the address - an NSString, an
NSNotification - and touchHLE aborted with

    Object 0x... (class "_touchHLE_NSString") does not respond to selector
    "incrementCount:"!                                  (exit -1073741819)

The emulator-side fix (stale-observer pruning in
`src/frameworks/foundation/ns_notification_center.rs`) stops that crash, but it
cannot stop an address being reused by *another `ZFQuestRequirement`*, in which
case the stale entry silently delivers an extra `incrementCount:`.  v28fix
removes the dangling entries at the source.

What v28fix changes
-------------------
`-stopListening` now does **both** jobs, in this order:

    NSNotificationCenter *center = [NSNotificationCenter defaultCenter];
    [center removeObserver:self];                  // v11fix, kept
    for (ZFQuestRequirement *req in self.requirements)
        [center removeObserver:req];               // original binary, restored

The v11 counting fix is preserved exactly: the notification itself is still
unregistered, which is the part that stopped the zeroing.  Nothing else in the
v10/v11 fix is touched (the `addUserData:` / `readUserData:` factory sites stay
as they are).

Why restoring the loop cannot re-break the counting fix
------------------------------------------------------
`removeObserver:` matches by pointer, and the two object sets are disjoint:
`-initWithID:loadSprite:` reads `Quests.plist` and builds a **fresh**
`NSMutableArray` of fresh `ZFQuestRequirement` objects into its own ivar
`+0x128` (sub9 `0x109a1e`..`0x109a48`).  GameData's throwaway notification
therefore owns different requirement objects than any live quest, so the
throwaway's loop can only unregister its own.  This is also precisely what the
unpatched game did.

Why the body is not a byte-for-byte copy of the original
-------------------------------------------------------
The original loop used fast enumeration
(`countByEnumeratingWithState:objects:count:`), which needs ~0x40 bytes of
state setup.  Original body (0xbe) + the new `removeObserver:self` call (~0x0e)
would be ~0xcc bytes, but v11fix left only the method's own 0xc0-byte slot
(0x10a1dc..0x10a29c) - so a byte-for-byte restore would need a code cave.
Instead the loop uses `count` + `objectAtIndex:`, which is equivalent here
(the array is not mutated during the loop) and assembles to 0x8a bytes, fitting
in place.  Both selectors are ordinary `NSArray` methods already used elsewhere
in this binary.

Sites (both slices; touchHLE executes sub9, sub6 is patched for symmetry)
------------------------------------------------------------------------
    sub9 0x10a1dc..0x10a29c  body  -> new body + nop padding
    sub6 0x16a5f8..0x16a700  body  -> new body + `mov r0,r0` padding
    sub6 0x16a700..0x16a718  pool  -> 6 absolute slot addresses

The sub6 pool is the method's own literal-pool slot (v11fix had retargeted it
for its 3-word body); v28fix rewrites all 6 words for its 6 loads.  Both
regions are guarded by sha256 of the exact v27fix bytes.
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
INPUT_NAME = f"{BASE}.fixed-fonts-v27fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v28fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v28fix.report.json"

INPUT_ZIP_SHA256 = "3D4CA38B66FAA55CA476FD4417443E814848BE44D978594E604EF81003AAC131"
INPUT_EXEC_SHA256 = "CE84E9C86A40500F7F96D40A7C22D73EE424A92C06CB6C18D5E4B1E2ABEE6E3A"

OBJC_MSGSEND = {6: 0x393FE0, 9: 0x2D014C}

# --------------------------------------------------------------- sub9 (Thumb)
SUB9_BASE = 0x10A1DC
SUB9_END = 0x10A29C
SLOT9 = {
    "nc": 0x399EAC,             # __objc_classrefs slot -> NSNotificationCenter
    "defaultCenter": 0x393CCC,  # __objc_selrefs slots
    "removeObserver": 0x393D4C,
    "requirements": 0x396298,
    "count": 0x393AA8,
    "objectAtIndex": 0x393AE0,
}

# ---------------------------------------------------------------- sub6 (ARM)
SUB6_BASE = 0x16A5F8
SUB6_CODE_END = 0x16A700
SUB6_POOL = 0x16A700
SUB6_END = 0x16A718
SLOT6 = {
    "nc": 0x45DF24,
    "defaultCenter": 0x457D44,
    "removeObserver": 0x457DC4,
    "requirements": 0x45A310,
    "count": 0x457B20,
    "objectAtIndex": 0x457B58,
}
POOL6_ORDER = ["nc", "defaultCenter", "removeObserver", "requirements", "count",
               "objectAtIndex"]
POOL6_INDEX = {name: i for i, name in enumerate(POOL6_ORDER)}

# sha256 of the exact v27fix bytes each region replaces
GUARDS = {
    (9, SUB9_BASE, SUB9_END):
        "3f27d334b6dd50f9861a9976b9f64397844d9411dd57392a4a42c85f24420080",
    (6, SUB6_BASE, SUB6_CODE_END):
        "824d7bda74a5cc5f1c13b58861bce85795a07373e275a1584d93a6ea19eee703",
    (6, SUB6_POOL, SUB6_END):
        "ede9e7ef1e636a1174fd62d28e41cbc686e080486047908fd60123d4bbfdb3d0",
}

# Regions earlier patches own; v28fix must not touch them.  The two
# stopListening regions are deliberately absent - they are what v28fix repairs.
FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810), (0x16D594, 0x16D5AC), (0x16D5B0, 0x16D5E0),
        (0x177534, 0x17753F),
        # v10fix factory sites
        (0x186D40, 0x186D44), (0x186D44, 0x186D48), (0x186D50, 0x186D54),
        (0x187DCC, 0x187DD0), (0x187DD0, 0x187DD4), (0x187DD8, 0x187DDC)],
    9: [(0x14F6C, 0x151C0), (0x10C470, 0x10C486), (0x10C490, 0x10C4C0),
        (0x1138A0, 0x1138C5), (0x1138C8, 0x1138F3), (0x1138F4, 0x113909),
        (0x76D0E, 0x76D12),                       # v27fix vmov constant
        (0x11F43A, 0x11F43E), (0x11F43C, 0x11F440), (0x11F440, 0x11F444),
        (0x120030, 0x120034), (0x120032, 0x120036), (0x120038, 0x12003C)],
}


# ------------------------------------------------------------------ assembler
def _thumb_mat(reg: int, addr: int) -> list[str]:
    return [f"movw r{reg}, #{addr & 0xFFFF}",
            f"movt r{reg}, #{(addr >> 16) & 0xFFFF}"]


def sub9_source() -> str:
    g, s = SLOT9, OBJC_MSGSEND[9]
    lines = ["push {r4, r5, r6, r7, lr}", "sub sp, #0xc", "mov r4, r0"]
    lines += _thumb_mat(0, g["nc"]) + ["ldr r0, [r0]"]
    lines += _thumb_mat(1, g["defaultCenter"]) + ["ldr r1, [r1]", f"blx #{s}"]
    lines += ["mov r5, r0"]
    lines += _thumb_mat(1, g["removeObserver"]) + [
        "ldr r1, [r1]", "mov r0, r5", "mov r2, r4", f"blx #{s}"]
    lines += ["mov r0, r4"]
    lines += _thumb_mat(1, g["requirements"]) + ["ldr r1, [r1]", f"blx #{s}"]
    lines += ["mov r6, r0", "mov r0, r6"]
    lines += _thumb_mat(1, g["count"]) + ["ldr r1, [r1]", f"blx #{s}"]
    lines += ["str r0, [sp]", "movs r7, #0",
              "loop9:", "ldr r3, [sp]", "cmp r7, r3", "bhs done9", "mov r0, r6"]
    lines += _thumb_mat(1, g["objectAtIndex"]) + [
        "ldr r1, [r1]", "mov r2, r7", f"blx #{s}"]
    lines += ["mov r2, r0", "mov r0, r5"]
    lines += _thumb_mat(1, g["removeObserver"]) + ["ldr r1, [r1]", f"blx #{s}"]
    lines += ["adds r7, #1", "b loop9",
              "done9:", "add sp, #0xc", "pop {r4, r5, r6, r7, pc}"]
    return "\n".join(t if t.endswith(":") else "    " + t for t in lines)


SUB6_BODY = [
    "mov r4, r0", "nc", "ldr r0, [r0]", "defaultCenter",
    f"bl #{OBJC_MSGSEND[6]}", "mov r5, r0", "removeObserver", "mov r0, r5",
    "mov r2, r4", f"bl #{OBJC_MSGSEND[6]}", "mov r0, r4", "requirements",
    f"bl #{OBJC_MSGSEND[6]}", "mov r6, r0", "mov r0, r6", "count",
    f"bl #{OBJC_MSGSEND[6]}", "mov sl, r0", "mov r8, #0",
    "loop6:", "cmp r8, sl", "bcs done6", "mov r0, r6", "objectAtIndex",
    "mov r2, r8", f"bl #{OBJC_MSGSEND[6]}", "mov r2, r0", "mov r0, r5",
    "removeObserver", f"bl #{OBJC_MSGSEND[6]}", "add r8, r8, #1", "b loop6",
    "done6:", "sub sp, r7, #0x18", "pop {r8, sl, fp}",
    "pop {r4, r5, r6, r7, pc}",
]


def sub6_source() -> str:
    """ARM source; pool-name entries become `ldr rX, [pc, #imm]`.

    The instruction index drives the pc-relative offset, so labels must not
    advance it (every ARM instruction is 4 bytes, so `base + 4*i` is exact).
    """
    out: list[str] = []
    idx = 0
    for text in SUB6_BODY:
        if text.endswith(":"):
            out.append(text)
            continue
        if text in POOL6_INDEX:
            addr = SUB6_BASE + 4 * idx
            imm = (SUB6_POOL + 4 * POOL6_INDEX[text]) - (addr + 8)
            if not 0 <= imm < 4096:
                raise ValueError(f"pool offset for {text} out of range: {imm}")
            reg = 0 if text == "nc" else 1
            out.append(f"ldr r{reg}, [pc, #{imm}]")
        else:
            out.append(text)
        idx += 1
    return "\n".join(t if t.endswith(":") else "    " + t for t in out)


def assemble() -> tuple[bytes, bytes, bytes]:
    """Assemble both bodies. Returns (sub9 body, sub6 code, sub6 pool)."""
    from keystone import KS_ARCH_ARM, KS_MODE_ARM, KS_MODE_THUMB, Ks

    enc9, _ = Ks(KS_ARCH_ARM, KS_MODE_THUMB).asm(sub9_source(), SUB9_BASE)
    enc6, _ = Ks(KS_ARCH_ARM, KS_MODE_ARM).asm(sub6_source(), SUB6_BASE)
    body9 = bytes(enc9)
    code6 = bytes(enc6)
    pool6 = b"".join(SLOT6[n].to_bytes(4, "little") for n in POOL6_ORDER)

    if len(body9) > SUB9_END - SUB9_BASE:
        raise ValueError(f"sub9 body {len(body9)} bytes does not fit")
    if len(code6) > SUB6_CODE_END - SUB6_BASE:
        raise ValueError(f"sub6 code {len(code6)} bytes does not fit")
    if len(pool6) != SUB6_END - SUB6_POOL:
        raise ValueError("sub6 pool size mismatch")

    body9 += struct.pack("<H", 0xBF00) * ((SUB9_END - SUB9_BASE - len(body9)) // 2)
    code6 += struct.pack("<I", 0xE1A00000) * (
        (SUB6_CODE_END - SUB6_BASE - len(code6)) // 4)
    if len(body9) != SUB9_END - SUB9_BASE or len(code6) != SUB6_CODE_END - SUB6_BASE:
        raise ValueError("padding failed to reach the region size")
    return body9, code6, pool6


# ------------------------------------------------------------------ verifiers
def disasm(subtype: int, addr: int, raw: bytes) -> list[Any]:
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if subtype == 6 else CS_MODE_THUMB)
    md.detail = True
    return list(md.disasm(raw, addr))


def verify_sub9(body: bytes) -> dict[str, Any]:
    """Structural check of the Thumb body: calls, selectors, loop, stack."""
    ins = disasm(9, SUB9_BASE, body)
    real = [i for i in ins if i.mnemonic not in ("nop",)]
    calls = [(i.address, i.mnemonic, i.operands[0].imm)
             for i in real if i.mnemonic in ("bl", "blx")]
    if len(calls) != 6:
        raise ValueError(f"sub9: expected 6 calls, found {len(calls)}")
    for addr, mn, tgt in calls:
        if tgt != OBJC_MSGSEND[9]:
            raise ValueError(f"sub9 {addr:#x}: call to {tgt:#x}, not objc_msgSend")
        if mn != "blx":
            raise ValueError(f"sub9 {addr:#x}: objc_msgSend must be blx in Thumb")

    # each call must have the right selector in r1, loaded from the right slot.
    # Track movw/movt per register: the class materialisation also loads r0, so
    # a naive "last two literals" check would be order-dependent and could pass
    # by luck.
    order = ["defaultCenter", "removeObserver", "requirements", "count",
             "objectAtIndex", "removeObserver"]
    for (addr, _mn, _t), name in zip(calls, order):
        want = SLOT9[name]
        got: int | None = None
        for i in real:
            if i.address >= addr:
                break
            if i.mnemonic in ("movw", "movt") and i.op_str.startswith("r1,"):
                imm = i.operands[1].imm
                if i.mnemonic == "movw":
                    got = ((got or 0) & 0xFFFF0000) | imm
                else:
                    got = ((got or 0) & 0xFFFF) | (imm << 16)
            elif i.mnemonic in ("mov", "ldr") and i.op_str.startswith("r1,"):
                # any other write to r1 invalidates the tracked value
                if i.mnemonic == "mov":
                    got = None
        if got != want:
            raise ValueError(
                f"sub9 {addr:#x}: r1 selector slot {got if got is None else hex(got)}, "
                f"expected {want:#x} ({name})")

    text = " ; ".join(f"{i.mnemonic} {i.op_str}" for i in real)
    for needle in ("str r0, [sp]", "ldr r3, [sp]", "adds r7, #1",
                   "add sp, #0xc", "pop {r4, r5, r6, r7, pc}",
                   "mov r2, r4", "mov r2, r0", "mov r2, r7"):
        if needle not in text:
            raise ValueError(f"sub9: missing `{needle}`")

    # loop back-edge must land on the count reload
    back = [i for i in real if i.mnemonic == "b" and i.operands[0].imm < i.address]
    if len(back) != 1:
        raise ValueError(f"sub9: expected 1 backward branch, found {len(back)}")
    target = next(i for i in real if i.address == back[0].operands[0].imm)
    if (target.mnemonic, target.op_str) != ("ldr", "r3, [sp]"):
        raise ValueError(f"sub9: loop head is `{target.mnemonic} {target.op_str}`")

    # both exits of the compare must be a forward branch to the epilogue
    exit_br = [i for i in real if i.mnemonic == "bhs"]
    if len(exit_br) != 1:
        raise ValueError("sub9: expected one `bhs` loop guard")
    epilogue = next(i for i in real if i.mnemonic == "add" and i.op_str == "sp, #0xc")
    if exit_br[0].operands[0].imm != epilogue.address:
        raise ValueError("sub9: `bhs` does not target the epilogue")

    return {"instructions": len(ins), "calls": [[hex(a), m, hex(t)]
                                                for a, m, t in calls],
            "loop_head": hex(target.address), "epilogue": hex(epilogue.address)}


def verify_sub6(code: bytes, pool: bytes) -> dict[str, Any]:
    """Structural check of the ARM body, including every pool load target."""
    ins = [i for i in disasm(6, SUB6_BASE, code) if i.mnemonic != "mov"
           or i.op_str != "r0, r0"]
    calls = [(i.address, i.operands[0].imm) for i in ins if i.mnemonic == "bl"]
    if len(calls) != 6:
        raise ValueError(f"sub6: expected 6 calls, found {len(calls)}")
    for addr, tgt in calls:
        if tgt != OBJC_MSGSEND[6]:
            raise ValueError(f"sub6 {addr:#x}: call to {tgt:#x}, not objc_msgSend")

    loads = []
    for i in ins:
        if i.mnemonic == "ldr" and "[pc," in i.op_str:
            imm = int(i.op_str.split("#")[1].rstrip("]"), 0)
            loads.append((i.address, i.address + 8 + imm))
    if len(loads) != 7:
        raise ValueError(f"sub6: expected 7 pool loads, found {len(loads)}")

    order = ["nc", "defaultCenter", "removeObserver", "requirements", "count",
             "objectAtIndex", "removeObserver"]
    for (addr, target), name in zip(loads, order):
        if not SUB6_POOL <= target < SUB6_END:
            raise ValueError(f"sub6 {addr:#x}: load target {target:#x} outside pool")
        off = target - SUB6_POOL
        got = struct.unpack_from("<I", pool, off)[0]
        if got != SLOT6[name]:
            raise ValueError(
                f"sub6 {addr:#x}: pool word {target:#x} = {got:#x}, expected "
                f"{SLOT6[name]:#x} ({name})")

    text = " ; ".join(f"{i.mnemonic} {i.op_str}" for i in ins)
    for needle in ("mov r2, r4", "mov r2, r0", "mov r2, r8", "mov r8, #0",
                   "add r8, r8, #1", "sub sp, r7, #0x18", "pop {r8, sl, fp}",
                   "pop {r4, r5, r6, r7, pc}"):
        if needle not in text:
            raise ValueError(f"sub6: missing `{needle}`")

    back = [i for i in ins if i.mnemonic == "b" and i.operands[0].imm < i.address]
    if len(back) != 1:
        raise ValueError(f"sub6: expected 1 backward branch, found {len(back)}")
    target = next(i for i in ins if i.address == back[0].operands[0].imm)
    if (target.mnemonic, target.op_str) != ("cmp", "r8, sl"):
        raise ValueError(f"sub6: loop head is `{target.mnemonic} {target.op_str}`")

    guard = [i for i in ins if i.mnemonic in ("bcs", "bhs")]
    if len(guard) != 1:
        raise ValueError("sub6: expected one `bcs` loop guard")
    epilogue = next(i for i in ins if i.mnemonic == "sub" and i.op_str == "sp, r7, #0x18")
    if guard[0].operands[0].imm != epilogue.address:
        raise ValueError("sub6: `bcs` does not target the epilogue")

    return {"instructions": len(ins), "calls": [[hex(a), hex(t)] for a, t in calls],
            "pool_loads": [[hex(a), hex(t)] for a, t in loads],
            "loop_head": hex(target.address), "epilogue": hex(epilogue.address)}


def _reg_list(ins) -> list[int]:
    """Register list of a push/pop.

    capstone 5 models `push {r4, r5, r6, r7, lr}` as one operand *per register*
    (each with `.reg`), so collect across all operands.
    """
    regs: list[int] = []
    for op in ins.operands:
        multi = getattr(op, "regs", None)
        if multi:
            regs.extend(multi)
            continue
        reg = getattr(op, "reg", None)
        if isinstance(reg, (list, tuple)):
            regs.extend(reg)
        elif reg:
            regs.append(reg)
    return regs


def _find(ins, pred, what: str):
    """First matching instruction, or a clear ValueError."""
    for i in ins:
        if pred(i):
            return i
    raise ValueError(f"missing {what}")


def verify_stack_balance(body9: bytes | None = None,
                         code6: bytes | None = None) -> dict[str, Any]:
    """Both bodies must leave SP exactly as they found it.

    Takes the bytes to check (defaults to a fresh assembly).  It must NOT
    re-assemble internally: the point is to validate the image being written.
    """
    from capstone.arm_const import ARM_OP_REG, ARM_REG_SP

    if body9 is None or code6 is None:
        fresh9, fresh6, _pool = assemble()
        body9 = body9 if body9 is not None else fresh9
        code6 = code6 if code6 is not None else fresh6

    out = {}
    ins9 = [i for i in disasm(9, SUB9_BASE, body9) if i.mnemonic != "nop"]
    push = _find(ins9, lambda i: i.mnemonic == "push", "sub9 prologue push")
    if len(_reg_list(push)) != 5:
        raise ValueError("sub9: prologue must push 5 registers")
    sub = _find(ins9, lambda i: i.mnemonic == "sub" and i.op_str == "sp, #0xc",
                "sub9 `sub sp, #0xc`")
    add = _find(ins9, lambda i: i.mnemonic == "add" and i.op_str == "sp, #0xc",
                "sub9 `add sp, #0xc`")
    pop = _find(ins9, lambda i: i.mnemonic == "pop", "sub9 epilogue pop")
    if len(_reg_list(pop)) != 5:
        raise ValueError("sub9: epilogue must pop 5 registers")
    if not (push.address < sub.address < add.address < pop.address):
        raise ValueError("sub9: stack adjustments are out of order")
    # no other instruction may touch SP
    others = [i for i in ins9
              if i not in (push, sub, add, pop)
              and i.mnemonic in ("sub", "add", "push", "pop")
              and i.operands and i.operands[0].type == ARM_OP_REG
              and i.operands[0].reg == ARM_REG_SP]
    if others:
        raise ValueError(
            "sub9: unexpected SP adjustments " + str([f"{i.mnemonic} {i.op_str}"
                                                      for i in others]))
    out["sub9"] = {"push": hex(push.address), "sub": hex(sub.address),
                   "add": hex(add.address), "pop": hex(pop.address),
                   "balanced": True}

    # sub6: the prologue/epilogue live outside the patched region; the body
    # must not touch sp at all except through the original `sub sp, r7, #0x18`.
    ins6 = [i for i in disasm(6, SUB6_BASE, code6)
            if not (i.mnemonic == "mov" and i.op_str == "r0, r0")]
    sp_writes = [i for i in ins6 if i.mnemonic in ("sub", "add", "push", "pop")
                 and i.operands and i.operands[0].type == ARM_OP_REG
                 and i.operands[0].reg == ARM_REG_SP]
    if len(sp_writes) != 1 or sp_writes[0].op_str != "sp, r7, #0x18":
        raise ValueError(f"sub6: unexpected SP adjustments {sp_writes}")
    out["sub6"] = {"sp_writes": [f"{i.mnemonic} {i.op_str}" for i in sp_writes],
                   "balanced": True}
    return out


# ------------------------------------------------------------------ self test
def self_test() -> list[str]:
    """Assembly must be stable and structurally correct before any write."""
    notes = []
    body9, code6, pool6 = assemble()
    notes.append(f"sub9 body {len(body9)} bytes in {SUB9_END - SUB9_BASE}")
    notes.append(f"sub6 code {len(code6)} bytes in {SUB6_CODE_END - SUB6_BASE}")
    notes.append(f"sub6 pool {len(pool6)} bytes in {SUB6_END - SUB6_POOL}")
    body9b, code6b, pool6b = assemble()
    if (body9, code6, pool6) != (body9b, code6b, pool6b):
        raise ValueError("assembly is not deterministic")
    notes.append("assembly is deterministic")
    notes.append("sub9 sha256 " + hashlib.sha256(body9).hexdigest()[:16])
    notes.append("sub6 sha256 " + hashlib.sha256(code6 + pool6).hexdigest()[:16])
    verify_sub9(body9)
    notes.append("sub9 structure verified (6 calls, selectors, loop, epilogue)")
    verify_sub6(code6, pool6)
    notes.append("sub6 structure verified (6 calls, 7 pool loads, loop, epilogue)")
    verify_stack_balance()
    notes.append("stack balance verified in both slices")
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
    if sha256(source).upper() != INPUT_ZIP_SHA256:
        raise ValueError(f"unexpected input archive sha256 {sha256(source)}")
    with zipfile.ZipFile(args.input) as archive:
        original = archive.read(EXECUTABLE)
    if sha256(original).upper() != INPUT_EXEC_SHA256:
        raise ValueError(f"unexpected input executable sha256 {sha256(original)}")

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != {6, 9}:
        raise ValueError("unexpected FAT slice set")

    body9, code6, pool6 = assemble()
    replacements = [(9, SUB9_BASE, SUB9_END, body9),
                    (6, SUB6_BASE, SUB6_CODE_END, code6),
                    (6, SUB6_POOL, SUB6_END, pool6)]

    out = bytearray(original)
    applied: list[dict[str, Any]] = []
    for subtype, lo, hi, new in replacements:
        for flo, fhi in FORBIDDEN_PRIOR.get(subtype, []):
            if lo < fhi and flo < hi:
                raise ValueError(f"sub{subtype} {lo:#x}..{hi:#x} overlaps "
                                 f"prior patch region {flo:#x}..{fhi:#x}")
        sl = slices[subtype]
        a = sl.addr_to_file(lo)
        b = sl.addr_to_file(hi - 1) + 1
        raw = sl.data[a:b]
        if len(raw) != hi - lo:
            raise ValueError(f"sub{subtype} {lo:#x}: region is not contiguous")
        want = GUARDS[(subtype, lo, hi)]
        got = hashlib.sha256(raw).hexdigest()
        if got != want:
            raise ValueError(f"sub{subtype} {lo:#x}..{hi:#x}: v27fix bytes "
                             f"differ (sha {got} != {want})")
        absolute = descriptors[subtype]["offset"] + a
        if bytes(out[absolute:absolute + len(raw)]) != raw:
            raise ValueError(f"sub{subtype} {lo:#x}: unexpected bytes in output")
        out[absolute:absolute + len(new)] = new
        applied.append({"subtype": subtype, "addr": f"{lo:#08x}",
                        "end": f"{hi:#08x}", "file_offset": absolute,
                        "len": len(new), "v27_sha256": got,
                        "new_sha256": hashlib.sha256(new).hexdigest(),
                        "note": {
                            (9, SUB9_BASE): "stopListening body -> removeObserver:self "
                                            "+ per-requirement removeObserver: loop",
                            (6, SUB6_BASE): "stopListening body (ARM) -> same",
                            (6, SUB6_POOL): "stopListening literal pool -> 6 slot words",
                        }[(subtype, lo)]})

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    patched = bytes(out)

    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, patched, [list(r) for r in allowed]):
        raise ValueError("patched executable differs outside the intended ranges")

    for subtype, ranges in FORBIDDEN_PRIOR.items():
        sl = slices[subtype]
        for flo, fhi in ranges:
            a = sl.addr_to_file(flo)
            b = sl.addr_to_file(fhi - 1) + 1
            if original[a:b] != patched[a:b]:
                raise ValueError(f"sub{subtype} prior region {flo:#x} modified")

    # independent readback + structural re-verification of the patched image
    for s in applied:
        got = patched[s["file_offset"]:s["file_offset"] + s["len"]]
        if hashlib.sha256(got).hexdigest() != s["new_sha256"]:
            raise ValueError(f"readback mismatch at {s['addr']}")
    checks = {"sub9": verify_sub9(
                  patched[applied[0]["file_offset"]:
                          applied[0]["file_offset"] + applied[0]["len"]]),
              "sub6": verify_sub6(
                  patched[applied[1]["file_offset"]:
                          applied[1]["file_offset"] + applied[1]["len"]],
                  patched[applied[2]["file_offset"]:
                          applied[2]["file_offset"] + applied[2]["len"]])}
    checks["stack"] = verify_stack_balance(
        patched[applied[0]["file_offset"]:applied[0]["file_offset"] + applied[0]["len"]],
        patched[applied[1]["file_offset"]:applied[1]["file_offset"] + applied[1]["len"]])

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "supersedes": "fixed-fonts-v27fix.ipa",
        "root_cause": "v11fix replaced the whole body of -[ZFQuestNotification "
                      "stopListening] with removeObserver:self, deleting the "
                      "original per-ZFQuestRequirement removeObserver: loop. "
                      "NSNotificationCenter holds observers as raw unretained "
                      "pointers, so each released requirement left a dangling "
                      "entry; posting that notification then sent incrementCount: "
                      "to a recycled address (NSString / NSNotification) and "
                      "touchHLE aborted with exit code -1073741819.",
        "fix": "-stopListening now calls [[NSNotificationCenter defaultCenter] "
               "removeObserver:self] (the v11fix counting repair, unchanged) AND "
               "then unregisters every object in self.requirements, restoring the "
               "original binary's cleanup.",
        "counting_fix_preserved": "removeObserver: matches by pointer and each "
                                  "ZFQuestNotification builds its own requirement "
                                  "objects from Quests.plist into its own ivar "
                                  "+0x128, so the throwaway's loop cannot "
                                  "unregister a live quest's counters.",
        "loop_style": "count + objectAtIndex: instead of the original fast "
                      "enumeration: equivalent here (the array is not mutated) and "
                      "0x8a bytes instead of ~0xcc, so no code cave is needed.",
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "sites": applied,
        "site_count": len(applied),
        "structure_checks": checks,
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
                        "sha256": sha256(output),
                        "executable_sha256": sha256(patched)}
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {args.output.name}  ({len(output)} bytes)")
    print(f"  ipa sha256 = {report['output']['sha256']}")
    for s in applied:
        print(f"  sub{s['subtype']} {s['addr']}..{s['end']} +{s['len']:>4}  {s['note']}")
    print(f"report: {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

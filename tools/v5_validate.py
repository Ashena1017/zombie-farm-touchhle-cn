#!/usr/bin/env python3
"""Validate the v5 (subclass) font site table before it is trusted.

Three questions, none of which the census answers on its own:

  1. DECODE-BACK - does the replacement instruction actually produce the
     intended float? For ARM the immediate is a rotated 8-bit field, so getting
     the rotate wrong silently produces a different float.
  2. CHAIN - does the patched register still feed the font-size stack slot the
     site was chosen for? Tracked by taint propagation: the value may pass
     through an `orr rX, rY, #0x40000000` before being stored.
  3. LIVENESS - after the value reaches the slot, is the patched register reused
     for an unrelated purpose? If it is, the edit could corrupt that other use.

Register identity is taken from Capstone's own disassembly (`md.reg_name`) rather
than hand-decoded 4-bit fields, so the comparison is against the same enum space
Capstone reports.
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_SP

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import (EXECUTABLE, ROOT, all_methods,  # noqa: E402
                              classes_by_name)

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v4.ipa"

# (subtype, patch_addr, old_hex, new_hex, font_slot, want_float,
#  owning_class, owning_selector, label)
SITES = [
    (6, 0x16682C, "1a36a0e3", "1c36a0e3", 0xC, 24.0, "ZFAlertWindowFlurryOffer",
     "initWithWindow:", "FlurryOffer -initWithWindow:"),
    (6, 0x16E7BC, "1a36a0e3", "1c36a0e3", 0xC, 24.0, "ZFAlertWindowQuest",
     "initWithQuest:", "Quest -initWithQuest:"),
    (6, 0x16F240, "1ab6a0e3", "1cb6a0e3", 0xC, 24.0, "ZFAlertWindowQuestComplete",
     "initWithQuest:", "QuestComplete -initWithQuest:"),
    (6, 0x1A3950, "1a36a0e3", "1c36a0e3", 0x0, 24.0, "ZFAlertWindowFriendsList",
     "init", "FriendsList -init #1"),
    (6, 0x1A3C00, "1a36a0e3", "1c36a0e3", 0x0, 24.0, "ZFAlertWindowFriendsList",
     "init", "FriendsList -init #2"),
    (6, 0x1A81D8, "1a36a0e3", "1c36a0e3", 0x0, 24.0, "ZFAlertWindowGiftReceive",
     "initWithGifts:", "GiftReceive -initWithGifts:"),
    (6, 0x1A9654, "1a36a0e3", "1c36a0e3", 0x0, 24.0, "ZFAlertWindowGiftSelection",
     "initWithLevel:", "GiftSelection -initWithLevel:"),
    (6, 0x1B2020, "1726a0e3", "1926a0e3", 0xC, 18.0, "ZFAlertWindowPromo",
     "initWithWindow:withDictionary:", "Promo -initWithWindow:withDictionary:"),
    (6, 0x1B3528, "1726a0e3", "1926a0e3", 0xC, 18.0, "ZFAlertWindowPromo",
     "display", "Promo -display"),
    (6, 0x252B60, "1a96a0e3", "1c96a0e3", 0xC, 24.0, "ZFAlertWindowBrainSpinner",
     "displayResult", "BrainSpinner -displayResult"),

    (9, 0x10776C, "c4f2a010", "c4f2c010", 0xC, 24.0, "ZFAlertWindowFlurryOffer",
     "initWithWindow:", "FlurryOffer -initWithWindow:"),
    (9, 0x10D090, "c4f2a016", "c4f2c016", 0xC, 24.0, "ZFAlertWindowQuest",
     "initWithQuest:", "Quest -initWithQuest:"),
    (9, 0x10DA84, "c4f2a010", "c4f2c010", 0xC, 24.0, "ZFAlertWindowQuestComplete",
     "initWithQuest:", "QuestComplete -initWithQuest:"),
    (9, 0x134524, "c4f2a010", "c4f2c010", 0x0, 24.0, "ZFAlertWindowFriendsList",
     "init", "FriendsList -init #1"),
    (9, 0x13478A, "c4f2a010", "c4f2c010", 0x0, 24.0, "ZFAlertWindowFriendsList",
     "init", "FriendsList -init #2"),
    (9, 0x137B84, "c4f2a010", "c4f2c010", 0x0, 24.0, "ZFAlertWindowGiftReceive",
     "initWithGifts:", "GiftReceive -initWithGifts:"),
    (9, 0x138B84, "c4f2a010", "c4f2c010", 0x0, 24.0, "ZFAlertWindowGiftSelection",
     "initWithLevel:", "GiftSelection -initWithLevel:"),
    (9, 0x14007C, "c4f27012", "c4f29012", 0xC, 18.0, "ZFAlertWindowPromo",
     "display", "Promo -display"),
    (9, 0x1B35AC, "c4f2a016", "c4f2c016", 0xC, 24.0, "ZFAlertWindowBrainSpinner",
     "displayResult", "BrainSpinner -displayResult"),
]

fails = []
warns = []


def check(name, ok, detail=""):
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def decode_thumb_movt(raw):
    """Thumb-2 `movt Rd,#imm16` -> (rd, imm16), else None.

    Encoding: hw1 = 11110 i 10 1100 imm4 ; hw2 = 0 imm3 Rd imm8.
    So the fixed pattern of hw1 is everything except the `i` bit (0x400) and the
    imm4 nibble (0xF), i.e. mask 0xFBF0 must equal 0xF2C0.
    """
    f, s2 = struct.unpack_from("<HH", raw, 0)
    if (f & 0xFBF0) != 0xF2C0 or (s2 & 0x8000) != 0:
        return None
    imm4 = f & 0xF
    i = (f >> 10) & 1
    imm3 = (s2 >> 12) & 0x7
    rd = (s2 >> 8) & 0xF
    imm8 = s2 & 0xFF
    return rd, (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8


def decode_arm_mov_imm(raw):
    """ARM `mov Rd,#imm` -> (rd, value), else None."""
    w = struct.unpack_from("<I", raw, 0)[0]
    if (w & 0x0FE00000) != 0x03A00000:
        return None
    rd = (w >> 12) & 0xF
    rot = ((w >> 8) & 0xF) * 2
    imm8 = w & 0xFF
    val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8
    return rd, val


def thumb_base_before(md, sl, addr, rd_name, window=0x60):
    """Value of `rd` just before `addr`, from its nearest preceding write.

    The compiler builds the float as `movs rX,#0` (or `movw rX,#0`) followed by
    `movt rX,#0x41NN`. Searching for a `movw` alone is wrong: unrelated address
    computations also use `movw` on the same register earlier in the method and
    are superseded by the nearer `movs`. So walk backwards and take the *last*
    immediate-forming write to the register.
    """
    lo = addr - window
    # skipdata matters: without it Capstone stops at the first undecodable word
    # (literal pools are common in the middle of these methods), silently
    # truncating the search window.
    md.skipdata = True
    seq = list(md.disasm(sl.data[sl.addr_to_file(lo):sl.addr_to_file(addr)], lo))
    for ins in reversed(seq):
        if not ins.operands:
            continue
        ops = ins.operands
        if not (ops[0].type == ARM_OP_REG
                and ins.reg_name(ops[0].reg) == rd_name
                and (ops[0].access & 2)):
            continue
        m = ins.mnemonic
        if m in ("movs", "mov", "movw") and len(ops) >= 2:
            if ops[1].type == ARM_OP_IMM:
                return ops[1].imm & 0xFFFF, ins.address, m
            return None, ins.address, m  # register move: value unknown
        if m == "movt":
            continue  # same construction, keep looking further back
        return None, ins.address, m
    return None, None, None


def method_extent(sl, cls_name, selector):
    """(start, end) for one method, using every method start as the boundary."""
    byname = classes_by_name(sl)
    if cls_name not in byname:
        return None
    cls, info = byname[cls_name]
    target = None
    for m in all_methods(sl, cls, info):
        if m.selector == selector:
            target = m
            break
    if target is None:
        return None
    starts = sorted({(m.imp & ~1) for m in sl.methods if m.file_offset is not None})
    s = target.imp & ~1
    nxt = next((x for x in starts if x > s), None)
    return s, (nxt if nxt else s + 0x1000)


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    S = {sl.subtype: sl for sl in parse_fat(fat)}

    for (st, addr, oldhex, newhex, slot, want, cls_name, selector,
         label) in SITES:
        sl = S[st]
        thumb = st == 9
        print(f"\n=== sub{st} {addr:#x}  {label}  (want {want}) ===")
        o = sl.addr_to_file(addr)
        raw_now = sl.data[o:o + 4]
        check("site bytes match the table", raw_now.hex() == oldhex,
              f"found {raw_now.hex()}")
        newraw = bytes.fromhex(newhex)
        check("width preserved", len(newraw) == len(raw_now))
        if raw_now.hex() != oldhex:
            continue

        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True

        # ---- 1. decode-back ------------------------------------------------
        md_new = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md_new.detail = True
        ins_new = list(md_new.disasm(newraw, addr))
        check("replacement decodes to exactly one instruction",
              len(ins_new) == 1 and sum(i.size for i in ins_new) == len(newraw),
              f"{len(ins_new)} insn, {sum(i.size for i in ins_new)} bytes")
        if not ins_new or not ins_new[0].operands:
            continue
        ins0 = ins_new[0]
        rd_enum = ins0.operands[0].reg
        rd_name = ins0.reg_name(rd_enum)
        print(f"    replacement: {ins0.mnemonic} {ins0.op_str}   (dest {rd_name})")

        if thumb:
            d = decode_thumb_movt(newraw)
            check("decodes as Thumb movt", d is not None)
            if d:
                _, imm16 = d
                low, low_addr, low_mnem = thumb_base_before(md, sl, addr, rd_name)
                check("low half of the float comes from an immediate write",
                      low is not None,
                      f"{low_mnem} @ {low_addr:#x} = {low}" if low is not None
                      else f"nearest write @ {low_addr} is {low_mnem} (value unknown)")
                if low is None:
                    low = 0
                built = struct.unpack(
                    "<f", struct.pack("<I", (imm16 << 16) | low))[0]
                check("rebuilt float equals target", abs(built - want) < 1e-6,
                      f"0x{imm16:04x}:{low:04x} -> {built}")
        else:
            d = decode_arm_mov_imm(newraw)
            check("decodes as ARM mov", d is not None)
            if d:
                _, val = d
                built = struct.unpack(
                    "<f", struct.pack("<I", val | 0x40000000))[0]
                check("rebuilt float equals target", abs(built - want) < 1e-6,
                      f"{val:#x} | 0x40000000 -> {built}")

        # ---- 2/3. taint to the font slot, then liveness ---------------------
        ext = method_extent(sl, cls_name, selector)
        check(f"owner method {cls_name} -{selector} located", ext is not None)
        if ext is None:
            continue
        start, end = ext
        check("patch site lies inside its owner method", start <= addr < end,
              f"method {start:#x}..{end:#x}")

        sp_name = md.reg_name(ARM_REG_SP)
        tainted = {rd_name}
        reached_at = None
        reuse_after = []
        seq = list(md.disasm(sl.data[sl.addr_to_file(addr):
                                     sl.addr_to_file(addr) + (end - addr)], addr))
        for ins in seq:
            if ins.id == 0 or not ins.operands:
                continue
            # stop looking once we have passed the slot store AND the register
            # is overwritten (beyond that, reuse is harmless)
            if ins.address != addr:
                dsts = [ins.reg_name(op.reg) for op in ins.operands
                        if op.type == ARM_OP_REG and (op.access & 2)]
                if reached_at is not None and rd_name in dsts:
                    break
            # propagate taint through moves / orr / add with a tainted source
            srcs = {ins.reg_name(op.reg) for op in ins.operands
                    if op.type == ARM_OP_REG and (op.access & 1)}
            dsts = {ins.reg_name(op.reg) for op in ins.operands
                    if op.type == ARM_OP_REG and (op.access & 2)}
            # a store to [sp, #slot] whose value is tainted completes the chain
            if ins.mnemonic in ("str", "str.w", "vstr") and ins.operands:
                mem = ins.operands[-1]
                if (mem.type == ARM_OP_MEM
                        and ins.reg_name(mem.mem.base) == sp_name
                        and mem.mem.disp == slot):
                    valregs = {ins.reg_name(op.reg) for op in ins.operands[:-1]
                               if op.type == ARM_OP_REG}
                    if valregs & tainted:
                        reached_at = ins.address
                        continue
            if srcs & tainted:
                tainted |= dsts
            elif ins.address != addr:
                tainted -= dsts

        check(f"value reaches [sp,#{slot:#x}]", reached_at is not None,
              f"store at {reached_at:#x}" if reached_at else "NOT REACHED")

        # liveness: does anything depend on rd after the slot store?
        if reached_at is not None:
            after = [i for i in seq if i.address > reached_at]
            for ins in after:
                if ins.id == 0 or not ins.operands:
                    continue
                if any(op.type == ARM_OP_REG
                       and ins.reg_name(op.reg) == rd_name
                       and (op.access & 2) for op in ins.operands):
                    reuse_after.append(ins.address)
            if reuse_after:
                warns.append(
                    f"sub{st} {addr:#x} {label}: {rd_name} rewritten after the "
                    f"slot store at {[hex(x) for x in reuse_after[:3]]} - harmless "
                    f"only if the value is dead there")
                print(f"    [WARN] {rd_name} rewritten after the store at "
                      f"{[hex(x) for x in reuse_after[:3]]} (value is dead there)")
            else:
                print(f"    [PASS] {rd_name} not rewritten before the method ends")

    print("\n" + "=" * 72)
    if warns:
        print(f"{len(warns)} WARNING(S):")
        for w in warns:
            print(f"  - {w}")
    if fails:
        print(f"RESULT: {len(fails)} FAILURE(S)")
        for f in fails:
            print(f"  - {f}")
        raise SystemExit(1)
    print("RESULT: ALL SITES VALIDATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

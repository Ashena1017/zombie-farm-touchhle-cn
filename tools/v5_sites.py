#!/usr/bin/env python3
"""Resolve the exact patch bytes for each v5 (subclass) font site.

The census (`_zt/c13_final.py`) gives, per font call, the provenance chain -
the addresses of the instructions that materialised the float. This script
disassembles those chains and identifies the single instruction whose immediate
carries the mantissa, then emits the width-preserving replacement.

ARM:   20.0 (0x41a00000) is built as `mov rX,#0x1a00000` + a later
       `orr rX,rX,#0x40000000`; the edit is the mov's imm8 (0x1a -> 0x1c).
Thumb:  built as `movw rX,#0x0000` + `movt rX,#0x41a0`; the edit is the movt
       immediate (0x41a0 -> 0x41c0).
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v4.ipa"

# site -> (subtype, provenance addresses, old_float, new_float, label)
SITES = [
    # ---- title 20.0 -> 24.0 -------------------------------------------------
    (6, [0x252B60, 0x252B74, 0x252B9C], 20.0, 24.0, "BrainSpinner -displayResult"),
    (6, [0x16682C, 0x166834, 0x166838], 20.0, 24.0, "FlurryOffer -initWithWindow:"),
    (6, [0x1A3950, 0x1A3958, 0x1A395C], 20.0, 24.0, "FriendsList -init #1"),
    (6, [0x1A3C00, 0x1A3C08, 0x1A3C0C], 20.0, 24.0, "FriendsList -init #2"),
    (6, [0x1A81D8, 0x1A81E0, 0x1A81E4], 20.0, 24.0, "GiftReceive -initWithGifts:"),
    (6, [0x1A9654, 0x1A965C, 0x1A9660], 20.0, 24.0, "GiftSelection -initWithLevel:"),
    (6, [0x16E7BC, 0x16E7C4, 0x16E7CC], 20.0, 24.0, "Quest -initWithQuest:"),
    (6, [0x16F240, 0x16F260, 0x16F3D4], 20.0, 24.0, "QuestComplete -initWithQuest:"),

    (9, [0x1B349E, 0x1B34A6, 0x1B35AC, 0x1B35CE], 20.0, 24.0, "BrainSpinner -displayResult"),
    (9, [0x107756, 0x10775A, 0x10776C, 0x107770], 20.0, 24.0, "FlurryOffer -initWithWindow:"),
    (9, [0x13450C, 0x134510, 0x134524, 0x134528], 20.0, 24.0, "FriendsList -init #1"),
    (9, [0x134772, 0x134776, 0x13478A, 0x13478E], 20.0, 24.0, "FriendsList -init #2"),
    (9, [0x137B6C, 0x137B70, 0x137B84, 0x137B88], 20.0, 24.0, "GiftReceive -initWithGifts:"),
    (9, [0x138B6C, 0x138B70, 0x138B84, 0x138B8A], 20.0, 24.0, "GiftSelection -initWithLevel:"),
    (9, [0x10D00E, 0x10D01C, 0x10D090, 0x10D1BC], 20.0, 24.0, "Quest -initWithQuest:"),
    (9, [0x10DA5E, 0x10DA62, 0x10DA84, 0x10DA88], 20.0, 24.0, "QuestComplete -initWithQuest:"),

    # ---- body 15.0 -> 18.0 --------------------------------------------------
    (6, [0x1B2020, 0x1B2034, 0x1B204C], 15.0, 18.0, "Promo -initWithWindow:withDictionary:"),
    (6, [0x1B3528, 0x1B353C, 0x1B3550], 15.0, 18.0, "Promo -display"),
    (9, [0x140052, 0x140056, 0x14007C, 0x140084], 15.0, 18.0, "Promo -display"),
]


def f32_bits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def encode_arm_imm(value, prefer_rot=None):
    """Find (rotate, imm8) such that ROR(imm8, rotate*2) == value.

    Returns None when the value is not an ARM-modified-immediate. `prefer_rot`
    keeps the original instruction's rotation when it still works, so the edit
    stays as close to the compiler's own encoding as possible.
    """
    value &= 0xFFFFFFFF
    if prefer_rot is not None:
        r = prefer_rot * 2
        imm8 = ((value << r) | (value >> (32 - r))) & 0xFFFFFFFF if r else value
        if imm8 <= 0xFF:
            return prefer_rot, imm8
    for rot in range(16):
        r = rot * 2
        imm8 = ((value << r) | (value >> (32 - r))) & 0xFFFFFFFF if r else value
        if imm8 <= 0xFF:
            return rot, imm8
    return None


def decode_arm_imm(w):
    rot = ((w >> 8) & 0xF) * 2
    imm8 = w & 0xFF
    return ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8


def read_f32(sl, addr):
    """Decode the float that `mov rX,#imm` + `orr rX,rX,#0x40000000` builds."""
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    w = struct.unpack_from("<I", sl.data, sl.addr_to_file(addr))[0]
    hi = decode_arm_imm(w) | 0x40000000
    return struct.unpack("<f", struct.pack("<I", hi))[0], hi


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    S = {sl.subtype: sl for sl in parse_fat(fat)}

    print(f"##### {IPA}")
    print("targets: 20.0=0x%08x -> 24.0=0x%08x | 15.0=0x%08x -> 18.0=0x%08x\n"
          % (f32_bits(20.0), f32_bits(24.0), f32_bits(15.0), f32_bits(18.0)))

    table = {6: [], 9: []}
    for st, prov, oldf, newf, label in SITES:
        sl = S[st]
        thumb = st == 9
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        base = sl.addr_to_file(prov[0])
        lo = prov[0]
        hi = max(prov) + 4
        print(f"===== sub{st} {label}  (want {oldf} -> {newf}) =====")
        window = list(md.disasm(sl.data[base:base + (hi - lo) + 4], lo))
        cand = None
        for ins in window:
            tag = ""
            raw = ins.bytes
            if not thumb and ins.mnemonic in ("mov", "movw"):
                w = struct.unpack_from("<I", raw, 0)[0]
                val = decode_arm_imm(w)
                tag = f"  imm=0x{val:08x}"
                # The mov carries the low 25 bits of the float, not 24: bit 24 is
                # the top bit of the exponent (0x41a00000 & 0x1ffffff = 0x1a00000).
                MASK = 0x01FFFFFF
                old_hi = f32_bits(oldf) & MASK
                new_hi = f32_bits(newf) & MASK
                if val == old_hi and cand is None:
                    enc = encode_arm_imm(new_hi, prefer_rot=(w >> 8) & 0xF)
                    if enc is None:
                        print("  !!! new float is not an ARM immediate")
                    else:
                        rot, imm8 = enc
                        nw = ((w & 0xFFFFF000) | (rot << 8) | imm8)
                        # decode back to prove the replacement is right
                        back = decode_arm_imm(nw) | 0x40000000
                        bf = struct.unpack("<f", struct.pack("<I", back))[0]
                        assert bf == newf, f"decode-back gave {bf}"
                        cand = (ins.address, raw.hex(),
                                struct.pack("<I", nw).hex(),
                                f"mov #{val:#x} -> #{new_hi:#x} (f={bf})")
                        tag += "   <<<< CANDIDATE"
            elif thumb and ins.mnemonic == "movt":
                try:
                    val = int(ins.op_str.split("#")[1], 0)
                except Exception:
                    val = None
                if val is not None:
                    tag = f"  imm=0x{val:04x}"
                    if val == (f32_bits(oldf) >> 16) and cand is None:
                        neww = (f32_bits(newf) >> 16) & 0xFFFF
                        # Thumb-2 movt: 11110 i 10 1100 imm4 | 0 imm3 Rd imm8
                        hw1, hw2 = struct.unpack_from("<HH", raw, 0)
                        i = (hw1 >> 10) & 1
                        imm4 = hw1 & 0xF
                        imm3 = (hw2 >> 12) & 0x7
                        imm8 = hw2 & 0xFF
                        cur = (imm4 << 12) | (imm3 << 8) | imm8
                        n_i = (neww >> 11) & 1
                        n_imm4 = (neww >> 12) & 0xF
                        n_imm3 = (neww >> 8) & 0x7
                        n_imm8 = neww & 0xFF
                        nhw1 = (hw1 & ~0x040F) | (n_i << 10) | n_imm4
                        nhw2 = (hw2 & ~0x70FF) | (n_imm3 << 12) | n_imm8
                        cand = (ins.address, raw.hex(),
                                struct.pack("<HH", nhw1, nhw2).hex(),
                                f"movt #{cur:#06x} -> #{neww:#06x}")
                        tag += "   <<<< CANDIDATE"
            print(f"  {ins.address:#08x} {raw.hex():<10} {ins.mnemonic:<10} {ins.op_str}{tag}")
        if cand is None:
            print("  !!! NO CANDIDATE FOUND")
        else:
            addr, oldb, newb, note = cand
            if len(oldb) != len(newb):
                print(f"  !!! WIDTH MISMATCH {oldb} -> {newb}")
            print(f"  ==> PATCH {addr:#08x}  {oldb} -> {newb}   {note}")
            table[st].append((addr, oldb, newb, f"{label}: {note}"))
        print()

    print("\n" + "=" * 72)
    print("PATCH_SITES = {")
    for st in (6, 9):
        print(f"    {st}: [")
        for addr, oldb, newb, note in sorted(table[st]):
            print(f'        (0x{addr:06X}, "{oldb}", "{newb}", "{note}"),')
        print("    ],")
    print("}")
    print(f"\ntotals: sub6={len(table[6])} sub9={len(table[9])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compile the v4 helper-repair site table from v3 by exhaustive scan.

The repair has two halves:

  1. RETARGET - every intra-cave `bl` whose target is one of the two neutered
     entry points is redirected to that entry's body (ARM entry+8, Thumb
     entry+4). The entries themselves stay `bx lr`, so ObjC dispatch of
     `showRateIt` / `showTreeWorldPopUp` remains crash-safe, while the wrapper
     network regains the helper.

  2. DELTA ZERO - each helper body adds a float delta to `fontSize_` (+4.0 in
     the showRateIt helper, +3.0 in the showTreeWorldPopUp helper). v3 already
     pins the creation constants to absolute 24/18, so leaving these live would
     render 28/22. The `vadd.f32 s0,s0,s2` is replaced by a redundant
     `vldr s0,[r4,#0x190]`, which loads the same value back, making the store
     a no-op. Both forms are 4 bytes and the replacement encoding is already
     present verbatim in the same helper, so the width and semantics are
     certain.

This script only REPORTS. It emits the exact site list, and cross-checks that
nothing outside the two caves references the entry points in a way we would
break. It writes no files other than stdout.
"""
from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
DEFAULT_IPA = f"{BASE}.fixed-fonts-v3.ipa"

CAVES = {6: (0x1B464, 0x1B810), 9: (0x14F6C, 0x151C0)}
ENTRIES = {6: {0x1B464: 0x1B46C, 0x1B688: 0x1B690},
           9: {0x14F6C: 0x14F70, 0x15110: 0x15114}}
# The delta is removed by replacing `vadd.f32 s0, s0, s2` with a redundant
# `vldr s0, [r4, #0x190]`, which loads the value straight back so the following
# `vstr s0, [r4, #0x190]` becomes a no-op. Both are 4 bytes. The ARM and Thumb-2
# VFP encodings differ, so each slice gets its own pair; the replacement word is
# already present verbatim inside the same helper, which is the strongest
# possible evidence that the encoding is right for that slice.
VADD = {6: bytes.fromhex("010a30ee"), 9: bytes.fromhex("30ee010a")}
VLDR = {6: bytes.fromhex("640a94ed"), 9: bytes.fromhex("94ed640a")}


def u32(sl, a):
    o = sl.addr_to_file(a)
    return None if o is None else struct.unpack_from("<I", sl.data, o)[0]


def cstr(sl, a, n=120):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    b = sl.data[o:o + n]
    i = b.find(b"\0")
    return b[:i if i >= 0 else n].decode("utf-8", "replace")


def sec_name(sl, a):
    for x in sl.sections:
        if x.addr <= a < x.addr + x.size:
            return x.name
    return None


def owner_of(sl, addr):
    best = None
    for mm in sl.methods:
        if mm.file_offset is None:
            continue
        s = mm.imp & ~1
        if s <= addr and (best is None or s > best[0]):
            best = (s, mm)
    if not best:
        return "?"
    mm = best[1]
    return f"{mm.cls}[{mm.kind}] {mm.selector} +{addr - best[0]:#x}"


def encode_arm_bl(addr, target):
    off = target - (addr + 8)
    if off % 4:
        raise ValueError("unaligned ARM branch")
    imm = (off >> 2) & 0xFFFFFF
    return struct.pack("<I", 0xEB000000 | imm)


def encode_thumb_bl(addr, target):
    off = target - (addr + 4)
    if off % 2:
        raise ValueError("unaligned Thumb branch")
    imm32 = off & 0x1FFFFFF
    s = (imm32 >> 24) & 1
    i1 = (imm32 >> 23) & 1
    i2 = (imm32 >> 22) & 1
    imm10 = (imm32 >> 12) & 0x3FF
    imm11 = (imm32 >> 1) & 0x7FF
    j1 = ((~i1) & 1) ^ s
    j2 = ((~i2) & 1) ^ s
    hw1 = 0xF000 | (s << 10) | imm10
    hw2 = 0xD000 | (j1 << 13) | (1 << 12) | (j2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


def decode_bl(sl, addr, thumb):
    """Return (kind, target) for a branch at addr, or None."""
    o = sl.addr_to_file(addr)
    if o is None:
        return None
    if not thumb:
        w = struct.unpack_from("<I", sl.data, o)[0]
        if (w & 0x0E000000) != 0x0A000000:
            return None
        imm = w & 0xFFFFFF
        if imm & 0x800000:
            imm -= 1 << 24
        return ("bl" if (w & (1 << 24)) else "b", addr + 8 + (imm << 2))
    f, s2 = struct.unpack_from("<HH", sl.data, o)
    if (f & 0xF800) != 0xF000 or (s2 & 0xC000) != 0xC000:
        return None
    blx = (s2 & 0x1000) == 0
    sb = (f >> 10) & 1
    j1, j2 = (s2 >> 13) & 1, (s2 >> 11) & 1
    i1, i2 = (~(j1 ^ sb)) & 1, (~(j2 ^ sb)) & 1
    raw = ((sb << 24) | (i1 << 23) | (i2 << 22)
           | ((f & 0x3FF) << 12) | ((s2 & 0x7FF) << 1))
    if raw & (1 << 24):
        raw -= 1 << 25
    pc = addr + 4
    if blx:
        pc &= ~3
    return ("blx" if blx else "bl", pc + raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ipa", default=DEFAULT_IPA)
    args = ap.parse_args()

    src = ROOT / args.ipa
    with zipfile.ZipFile(src) as z:
        fat = z.read(EXECUTABLE)
    print(f"##### {args.ipa}")

    retarget, deltas = [], []
    for sl in parse_fat(fat):
        st = sl.subtype
        thumb = st == 9
        lo, hi = CAVES[st]
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        md.skipdata = True
        off = sl.addr_to_file(lo)
        print(f"\n===== sub{st} cave {lo:#x}..{hi:#x} =====")
        for ins in md.disasm(sl.data[off:off + (hi - lo)], lo):
            if ins.id == 0:
                continue
            if ins.mnemonic in ("bl", "blx", "b"):
                d = decode_bl(sl, ins.address, thumb)
                if d is None:
                    continue
                kind, tgt = d
                if tgt in ENTRIES[st]:
                    body = ENTRIES[st][tgt]
                    enc = (encode_thumb_bl if thumb else encode_arm_bl)
                    new = enc(ins.address, body)
                    retarget.append((st, ins.address, ins.bytes, new, tgt, body, kind))
                    print(f"  RETARGET {ins.address:#08x} {ins.bytes.hex()} -> "
                          f"{new.hex()}   {kind} {tgt:#x} -> {body:#x}")
            if ins.bytes == VADD[st]:
                new = VLDR[st]
                deltas.append((st, ins.address, ins.bytes, new))
                print(f"  DELTA    {ins.address:#08x} {ins.bytes.hex()} -> "
                      f"{new.hex()}   vadd.f32 s0,s0,s2 -> vldr s0,[r4,#0x190]")

    # ---- cross-checks -------------------------------------------------------
    print("\n===== cross-checks =====")
    print(f"retarget sites: {len(retarget)}   delta sites: {len(deltas)}")
    for st in (6, 9):
        n = sum(1 for s, *_ in retarget if s == st)
        d = sum(1 for s, *_ in deltas if s == st)
        print(f"  sub{st}: {n} retarget, {d} delta")

    # 1. every generated branch must decode back to the intended target
    print("\n-- round-trip: decode every re-encoded branch --")
    bad = 0
    for st, addr, old, new, tgt, body, kind in retarget:
        sl = next(s for s in parse_fat(fat) if s.subtype == st)
        # decode the NEW bytes directly
        if st == 9:
            f, s2 = struct.unpack_from("<HH", new, 0)
            sb = (f >> 10) & 1
            j1, j2 = (s2 >> 13) & 1, (s2 >> 11) & 1
            i1, i2 = (~(j1 ^ sb)) & 1, (~(j2 ^ sb)) & 1
            raw = ((sb << 24) | (i1 << 23) | (i2 << 22)
                   | ((f & 0x3FF) << 12) | ((s2 & 0x7FF) << 1))
            if raw & (1 << 24):
                raw -= 1 << 25
            got = addr + 4 + raw
        else:
            w = struct.unpack_from("<I", new, 0)[0]
            imm = w & 0xFFFFFF
            if imm & 0x800000:
                imm -= 1 << 24
            got = addr + 8 + (imm << 2)
        ok = got == body
        if not ok:
            bad += 1
        print(f"  sub{st} {addr:#08x} -> decoded {got:#x} expect {body:#x} "
              f"{'OK' if ok else 'MISMATCH'}")
    print(f"  mismatches: {bad}")

    # 2. every delta site's replacement word must already exist in the file
    print("\n-- replacement vldr bytes already present in each slice? --")
    for st in (6, 9):
        sl = next(s for s in parse_fat(fat) if s.subtype == st)
        want = VLDR[st]
        step = 4 if st == 6 else 2
        cnt = sum(1 for i in range(0, len(sl.data) - 4, step)
                  if sl.data[i:i + 4] == want)
        print(f"  sub{st}: {cnt} occurrence(s) of {want.hex()}")

    # 3. no branch from OUTSIDE a cave targets an entry (those stay bx lr)
    print("\n-- external branches landing on the neutered entries --")
    total_ext = 0
    for st in (6, 9):
        sl = next(s for s in parse_fat(fat) if s.subtype == st)
        thumb = st == 9
        lo, hi = CAVES[st]
        hits = []
        for sec in sl.sections:
            if sec.name != "__text":
                continue
            data = sl.data[sec.offset:sec.offset + sec.size]
            step = 4 if not thumb else 2
            for i in range(0, len(data) - 3, step):
                a = sec.addr + i
                d = decode_bl(sl, a, thumb)
                if d is None:
                    continue
                _, t = d
                if t in ENTRIES[st] and not (lo <= a < hi):
                    hits.append((a, t))
        total_ext += len(hits)
        print(f"  sub{st}: {len(hits)} external branch(es) to an entry")
        for a, t in hits:
            print(f"    {a:#08x} -> {t:#x}   from {owner_of(sl, a)}")
    print(f"  total: {total_ext}")

    # 4. record which ObjC methods have an IMP inside a cave (must stay put)
    print("\n-- ObjC methods whose IMP lies inside a cave (entries must remain) --")
    for st in (6, 9):
        sl = next(s for s in parse_fat(fat) if s.subtype == st)
        lo, hi = CAVES[st]
        for mm in sl.methods:
            if mm.file_offset is None:
                continue
            imp = mm.imp & ~1
            if lo <= imp < hi:
                print(f"  sub{st} {mm.cls}[{mm.kind}] {mm.selector} imp={mm.imp:#x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

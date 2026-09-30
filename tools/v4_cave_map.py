#!/usr/bin/env python3
"""Complete the cave map for the v4 helper repair, both slices.

Claude's session was cut off right as it started the Thumb side. This script
produces the annotated disassembly of both caves in the *v3* IPA (the new
baseline), resolving literals to selectors/CFStrings so the helper structure is
readable without guesswork.

It reports, per slice:
  * every float immediate (the +4.0 / +3.0 deltas we must zero),
  * every fontSize_ (+0x190) read/write,
  * every intra-cave `bl` with its target classified as DEAD ENTRY / BODY / other,
  * every inbound branch from outside the cave with its owning method.

READ-ONLY: writes nothing except stdout.
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

# Whole neutered promotion-method bodies (the "caves").
CAVES = {
    6: [(0x1B464, 0x1B810)],
    9: [(0x14F6C, 0x151C0)],
}
# The two entry points per slice that the crash fix turned into `bx lr`.
ENTRIES = {6: [0x1B464, 0x1B688], 9: [0x14F6C, 0x15110]}
FONTSIZE_OFF = 0x190


def u32(sl, a):
    o = sl.addr_to_file(a)
    return None if o is None else struct.unpack_from("<I", sl.data, o)[0]


def cstr(sl, a, n=160):
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


def resolve(sl, a):
    """Best-effort symbolic name for a pointer target."""
    s = sec_name(sl, a)
    if s == "__objc_selrefs":
        return f"SEL:{cstr(sl, u32(sl, a))!r}"
    if s == "__objc_methname":
        return f"METHNAME:{cstr(sl, a)!r}"
    if s == "__cfstring":
        p, ln = u32(sl, a + 8), u32(sl, a + 12)
        return f"CFSTR({cstr(sl, p, min((ln or 60) + 1, 160))!r})"
    if s == "__objc_classrefs":
        return f"CLASSREF(@{u32(sl, a):#x})"
    if s == "__objc_ivar":
        return f"IVAR(+{u32(sl, a):#x})"
    if s == "__objc_classname":
        return f"CLASSNAME:{cstr(sl, a)!r}"
    if s:
        return f"{s}@{a:#x}"
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


def branch_sources(sl, lo, hi, thumb):
    """External branches landing inside [lo,hi)."""
    hits = []
    for sec in sl.sections:
        if sec.name != "__text":
            continue
        data = sl.data[sec.offset:sec.offset + sec.size]
        base = sec.addr
        step = 4 if not thumb else 2
        for i in range(0, len(data) - 3, step):
            if not thumb:
                w = struct.unpack_from("<I", data, i)[0]
                if (w & 0x0E000000) != 0x0A000000:
                    continue
                imm = w & 0x00FFFFFF
                if imm & 0x800000:
                    imm -= 1 << 24
                tgt = base + i + 8 + (imm << 2)
                kind = "bl" if (w & (1 << 24)) else "b"
            else:
                f, s2 = struct.unpack_from("<HH", data, i)
                if (f & 0xF800) != 0xF000 or (s2 & 0xC000) != 0xC000:
                    continue
                blx = (s2 & 0x1000) == 0
                sb = (f >> 10) & 1
                j1, j2 = (s2 >> 13) & 1, (s2 >> 11) & 1
                i1, i2 = (~(j1 ^ sb)) & 1, (~(j2 ^ sb)) & 1
                raw = ((sb << 24) | (i1 << 23) | (i2 << 22)
                       | ((f & 0x3FF) << 12) | ((s2 & 0x7FF) << 1))
                if raw & (1 << 24):
                    raw -= 1 << 25
                pc = base + i + 4
                if blx:
                    pc &= ~3
                tgt = pc + raw
                kind = "blx" if blx else "bl"
            src = base + i
            if lo <= tgt < hi and not (lo <= src < hi):
                hits.append((src, tgt, kind))
    return hits


def dump_cave(sl, lo, hi, thumb):
    entries = ENTRIES[sl.subtype]
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    off = sl.addr_to_file(lo)
    lits = {}
    print(f"\n===== sub{sl.subtype} cave {lo:#x}..{hi:#x} "
          f"({'thumb' if thumb else 'arm'}) =====")
    for ins in md.disasm(sl.data[off:off + (hi - lo)], lo):
        m, ops = ins.mnemonic, ins.op_str
        note = ""
        if ins.id == 0:
            print(f"  {ins.address:#08x} {ins.bytes.hex():<8} .word")
            continue
        # literal pool tracking so [pc, rX] and add rX, pc resolve
        if m == "ldr" and "[pc, #" in ops:
            try:
                imm = int(ops.split("#")[1].rstrip("]"), 0)
            except ValueError:
                imm = None
            if imm is not None:
                v = u32(sl, ins.address + 8 + imm)
                if v is not None:
                    lits[ops.split(",")[0]] = v
                    tgt = (ins.address + 8 + v) & 0xFFFFFFFF
                    r = resolve(sl, tgt)
                    note = f"  ; lit={v:#x} -> {tgt:#x}" + (f" {r}" if r else "")
        elif m == "ldr" and "[pc, r" in ops:
            src = ops.split("[pc, ")[1].rstrip("]")
            d = lits.get(src)
            if d is not None:
                tgt = (ins.address + 8 + d) & 0xFFFFFFFF
                note = f"  ; ==> {tgt:#x} {resolve(sl, tgt) or ''}"
        elif m in ("add", "mov") and ", pc" in ops:
            srcreg = ops.split(",")[-1].strip()
            d = lits.get(srcreg)
            if d is not None:
                tgt = (ins.address + 8 + d) & 0xFFFFFFFF
                note = f"  ; ==> {tgt:#x} {resolve(sl, tgt) or ''}"
        elif m in ("bl", "blx") and ops.startswith("#"):
            t = int(ops[1:], 16)
            if t in (0x393FE0, 0x2D014C):
                note = "  ; objc_msgSend"
            elif lo <= t < hi:
                if t in entries:
                    note = "  ; <-- INTRA-CAVE [DEAD ENTRY]"
                elif any(t == e + 8 for e in entries):
                    note = "  ; <-- INTRA-CAVE [BODY entry+8]"
                else:
                    note = "  ; <-- INTRA-CAVE"
            else:
                note = f"  ; ext {sec_name(sl, t) or ''}"
        if f"#{FONTSIZE_OFF:#x}" in ops:
            note += "   <<<< fontSize_"
        if m in ("push", "pop"):
            note += "   <<<< boundary"
        if m.startswith("vmov.f") and "#" in ops:
            note += "   <<<< FLOAT IMM"
        print(f"  {ins.address:#08x} {ins.bytes.hex():<8} {m:<12} {ops}{note}")

    srcs = branch_sources(sl, lo, hi, thumb)
    print(f"\n  --- {len(srcs)} inbound branch(es) from live code ---")
    for s, t, k in srcs:
        tag = "DEAD ENTRY" if t in entries else (
            "BODY entry+8" if any(t == e + 8 for e in entries) else "other")
        print(f"    {s:#08x} {k:<3} -> {t:#08x}  [{tag}]  from {owner_of(sl, s)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ipa", default=DEFAULT_IPA)
    args = ap.parse_args()
    with zipfile.ZipFile(ROOT / args.ipa) as z:
        fat = z.read(EXECUTABLE)
    print(f"##### {args.ipa}")
    for sl in parse_fat(fat):
        for lo, hi in CAVES[sl.subtype]:
            dump_cave(sl, lo, hi, sl.subtype == 9)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

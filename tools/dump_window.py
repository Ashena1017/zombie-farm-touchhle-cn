#!/usr/bin/env python3
"""Dump a code window with every selector / CFString / class reference resolved.

Same resolution engine as the v4/v5 work: `ldr rX,[pc,#imm]` loads a *delta* in
these slices, and a later `ldr rY,[pc,rX]` or `add rY,pc,rX` turns it into the
real address. Conflating the two produces false references, so both are tracked.
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
DEFAULT_IPA = f"{BASE}.fixed-fonts-v5.ipa"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lo", type=lambda x: int(x, 0))
    ap.add_argument("hi", type=lambda x: int(x, 0))
    ap.add_argument("--sub", type=int, default=6)
    ap.add_argument("--ipa", default=DEFAULT_IPA)
    args = ap.parse_args()

    with zipfile.ZipFile(ROOT / args.ipa) as z:
        fat = z.read(EXECUTABLE)
    sl = next(s for s in parse_fat(fat) if s.subtype == args.sub)
    thumb = args.sub == 9

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None else struct.unpack_from("<I", sl.data, o)[0]

    def sec_name(a):
        for x in sl.sections:
            if x.addr <= a < x.addr + x.size:
                return x.name
        return None

    def cstr(a, n=90):
        o = sl.addr_to_file(a)
        if o is None:
            return None
        b = sl.data[o:o + n]
        i = b.find(b"\0")
        return b[:i if i >= 0 else n].decode("utf-8", "replace")

    def resolve(a):
        s = sec_name(a)
        if s == "__objc_selrefs":
            return f"SEL:{cstr(u32(a))!r}"
        if s == "__cfstring":
            dp, ln = u32(a + 8), u32(a + 12)
            return f"CFSTR({cstr(dp, min((ln or 60) + 1, 90))!r})"
        if s == "__objc_classrefs":
            return f"CLSREF(@{u32(a):#x})"
        if s == "__objc_methname":
            return f"METH:{cstr(a)!r}"
        if s == "__objc_classname":
            return f"CLSNAME:{cstr(a)!r}"
        if s:
            return f"{s}@{a:#x}"
        return None

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    o = sl.addr_to_file(args.lo)
    lits = {}
    print(f"##### sub{args.sub} {args.lo:#x}..{args.hi:#x}")
    for ins in md.disasm(sl.data[o:o + (args.hi - args.lo)], args.lo):
        m, ops = ins.mnemonic, ins.op_str
        note = ""
        if m == "ldr" and "[pc, #" in ops:
            try:
                imm = int(ops.split("#")[1].rstrip("]"), 0)
                base = ((ins.address + 4) & ~3) if thumb else (ins.address + 8)
                v = u32(base + imm)
                if v is not None:
                    lits[ops.split(",")[0]] = v
            except Exception:
                pass
        if "pc" in ops and m in ("add", "ldr", "mov"):
            # `ldr r1, [pc, r1]` -> the index register is "r1]" as split, so strip
            # brackets; otherwise every indexed load silently fails to resolve.
            src = ops.split(",")[-1].strip().rstrip("]").strip()
            d = lits.get(src)
            if d is not None:
                base = ((ins.address + 4) & ~3) if thumb else (ins.address + 8)
                tgt = (base + d) & 0xFFFFFFFF
                note = f"  ; ==> {tgt:#x} {resolve(tgt) or ''}"
        if m in ("bl", "blx") and ops.startswith("#"):
            t = int(ops[1:], 16)
            if t in (0x393FE0, 0x2D014C):
                note = "  ; objc_msgSend"
        print(f"  {ins.address:#08x} {ins.bytes.hex():<8} {m:<10} {ops}{note}")


if __name__ == "__main__":
    raise SystemExit(main())

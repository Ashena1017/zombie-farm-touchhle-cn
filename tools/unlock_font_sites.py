#!/usr/bin/env python3
"""Find every font-size slot in a method, both slices.

The unlock-confirm dialog (`ZFMarketMenu -unlockItem:`) builds a fresh body
label with `labelWithString:dimensions:alignment:fontName:fontSize:` and
installs it with `setBody1:`, so v3's `initWithWindow:` constants never reach
it -- exactly the "factory rebuild" idiom seen in Simple/SimpleChoice.

This walks a method, resolves float immediates built as
`mov rX,#0xNN00000` (+ later `orr rX,rX,#0x40000000`) on ARM, and reports the
instruction that materialises each font value together with the store slot, so
the patch site can be picked precisely.
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
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v5.ipa"

# label, subtype, start, end
REGIONS = [
    ("ZFMarketMenu -unlockItem:", 6, 0x69DFC, 0x6A7E0),
    ("ZFMarketMenu -unlockItem:", 9, None, None),   # resolved by name below
]

FONT_SLOT_SELECTORS = (
    "labelWithString:dimensions:alignment:fontName:fontSize:",
    "initWithString:dimensions:alignment:fontName:fontSize:",
    "labelWithString:fontName:fontSize:",
    "initWithString:fontName:fontSize:",
    "labelWithString:dimensions:hAlignment:fontName:fontSize:",
    "initWithString:dimensions:hAlignment:fontName:fontSize:",
)
SLOT = {
    "labelWithString:dimensions:alignment:fontName:fontSize:": 0xC,
    "initWithString:dimensions:alignment:fontName:fontSize:": 0xC,
    "labelWithString:dimensions:hAlignment:fontName:fontSize:": 0xC,
    "initWithString:dimensions:hAlignment:fontName:fontSize:": 0xC,
    "labelWithString:fontName:fontSize:": 0x0,
    "initWithString:fontName:fontSize:": 0x0,
}


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    slices = {sl.subtype: sl for sl in parse_fat(fat)}

    for label, st, start, end in REGIONS:
        sl = slices[st]
        thumb = st == 9

        def u32(a):
            o = sl.addr_to_file(a)
            return None if o is None else struct.unpack_from("<I", sl.data, o)[0]

        def sec_name(a):
            for x in sl.sections:
                if x.addr <= a < x.addr + x.size:
                    return x.name
            return None

        def cstr(a, n=80):
            o = sl.addr_to_file(a)
            if o is None:
                return None
            b = sl.data[o:o + n]
            i = b.find(b"\0")
            return b[:i if i >= 0 else n].decode("utf-8", "replace")

        if start is None:
            # find the IMP by name
            for m in sl.methods:
                if (m.selector or "") == "unlockItem:" and m.cls == "ZFMarketMenu":
                    start = m.imp & ~1
                    break
            if start is None:
                print(f"sub{st}: unlockItem: not found")
                continue
            starts = sorted({(m.imp & ~1) for m in sl.methods
                             if m.file_offset is not None})
            nxt = next((x for x in starts if x > start), None)
            end = nxt if nxt else start + 0x1000

        print(f"\n########## sub{st} {label}  {start:#x}..{end:#x} ##########")
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        md.skipdata = True
        o = sl.addr_to_file(start)
        lits = {}
        regimm = {}          # register -> candidate float bits from `mov`
        pending = []         # (addr, reg, value, bytes)
        for ins in md.disasm(sl.data[o:o + (end - start)], start):
            if ins.id == 0 or not ins.operands:
                continue
            m, ops = ins.mnemonic, ins.op_str
            pc = (ins.address + 4) & ~3 if thumb else ins.address + 8

            # literal pool resolution (both the delta load and the indexed load)
            if m == "ldr" and "[pc, #" in ops:
                try:
                    imm = int(ops.split("#")[1].rstrip("]"), 0)
                except ValueError:
                    imm = None
                if imm is not None:
                    v = u32(pc + imm)
                    if v is not None:
                        lits[ops.split(",")[0]] = v
            elif "pc" in ops and m in ("add", "ldr", "mov"):
                src = ops.split(",")[-1].strip().rstrip("]").strip()
                d = lits.get(src)
                if d is not None:
                    t = (pc + d) & 0xFFFFFFFF
                    if sec_name(t) == "__objc_selrefs":
                        sel = cstr(u32(t), 70)
                        if sel in SLOT:
                            print(f"   *** font-call {sel} @ {ins.address:#x} "
                                  f"(fontSize slot [sp,#{SLOT[sel]:#x}])")

            # float immediate construction
            if not thumb and m in ("mov", "movw") and len(ops) == 2 \
                    and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_IMM:
                w = struct.unpack_from("<I", ins.bytes, 0)[0]
                rot = ((w >> 8) & 0xF) * 2
                imm8 = w & 0xFF
                val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8
                regimm[ops[0].reg] = (val, ins.address, ins.bytes.hex())
                pending.append((ins.address, ops[0].reg, val, ins.bytes.hex()))
            elif thumb and m == "movt" and len(ops) == 2 \
                    and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_IMM:
                hi = ops[1].imm & 0xFFFF
                lo = 0
                # nearest preceding immediate write to the same register
                for a2, r2, v2, b2 in reversed(pending):
                    if r2 == ops[0].reg:
                        lo = v2 & 0xFFFF
                        break
                full = (hi << 16) | lo
                pending.append((ins.address, ops[0].reg, full, ins.bytes.hex()))
                f = struct.unpack("<f", struct.pack("<I", full))[0]

        # second pass: pair `orr rX, rX, #0x40000000` with the earlier mov
        print("   --- candidate float immediates feeding a font slot ---")
        for addr, reg, val, bhex in pending:
            # The `mov` carries the low 25 bits of the float (bit 24 is the top
            # bit of the exponent), so the valid range is <= 0x1FFFFFF -- not
            # "top byte clear", which would wrongly drop 14.0 (0x1600000).
            if val > 0x01FFFFFF:
                continue
            full = val | 0x40000000
            f = struct.unpack("<f", struct.pack("<I", full))[0]
            if 8.0 <= f <= 40.0:
                rn = None
                try:
                    rn = md.reg_name(reg)
                except Exception:
                    pass
                print(f"     {addr:#08x}  {bhex}  {rn} low={val:#x} "
                      f"-> float {f:g} (with orr #0x40000000)")
        # thumb movt values
        if thumb:
            for addr, reg, val, bhex in pending:
                f = struct.unpack("<f", struct.pack("<I", val))[0]
                if 8.0 <= f <= 40.0:
                    print(f"     {addr:#08x}  {bhex}  movt -> float {f:g}")


if __name__ == "__main__":
    raise SystemExit(main())

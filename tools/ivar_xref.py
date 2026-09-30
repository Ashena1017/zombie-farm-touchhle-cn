#!/usr/bin/env python3
"""Which methods reference a given ObjC ivar slot?

Answers the persistence question directly: if the quest-array ivars are written
by the save path but never read by the load path, quest progress cannot survive
a relaunch.

Reports every code site that resolves a register to the target `__objc_ivar`
address, together with the owning method.
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v5.ipa"
# __objc_ivar addresses discovered for the quest arrays (sub6).
TARGETS = {6: [0x47FB60, 0x47FB5C], 9: []}


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)

    want = {int(a, 0) for a in sys.argv[1:]} if len(sys.argv) > 1 else None

    for sl in parse_fat(fat):
        st = sl.subtype
        thumb = st == 9
        targets = want or set(TARGETS.get(st, []))
        if not targets:
            continue

        def u32(a):
            o = sl.addr_to_file(a)
            return None if o is None else struct.unpack_from("<I", sl.data, o)[0]

        def sec_name(a):
            for x in sl.sections:
                if x.addr <= a < x.addr + x.size:
                    return x.name
            return None

        def owner(addr):
            best = None
            for m in sl.methods:
                if m.file_offset is None:
                    continue
                s = m.imp & ~1
                if s <= addr and (best is None or s > best[0]):
                    best = (s, m)
            if not best:
                return "?"
            mm = best[1]
            return f"{mm.cls}[{mm.kind}] {mm.selector}+{addr - best[0]:#x}"

        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        md.skipdata = True

        print(f"\n########## sub{st} ##########")
        for tgt in sorted(targets):
            hits = []
            for sec in sl.sections:
                if sec.name != "__text":
                    continue
                lits = {}
                for ins in md.disasm(sl.data[sec.offset:sec.offset + sec.size],
                                     sec.addr):
                    if ins.id == 0 or not ins.operands:
                        continue
                    m, ops = ins.mnemonic, ins.op_str
                    if m == "ldr" and "[pc, #" in ops:
                        try:
                            imm = int(ops.split("#")[1].rstrip("]"), 0)
                        except ValueError:
                            continue
                        base = ((ins.address + 4) & ~3) if thumb else (ins.address + 8)
                        v = u32(base + imm)
                        if v is not None:
                            lits[ops.split(",")[0]] = v
                    elif "pc" in ops and m in ("add", "ldr", "mov"):
                        src = ops.split(",")[-1].strip().rstrip("]").strip()
                        d = lits.get(src)
                        if d is not None:
                            base = ((ins.address + 4) & ~3) if thumb else (ins.address + 8)
                            t = (base + d) & 0xFFFFFFFF
                            if t == tgt:
                                hits.append(ins.address)
            print(f"\n  === ivar {tgt:#x}: {len(hits)} reference site(s) ===")
            for a in hits:
                print(f"     {a:#08x}  {owner(a)}")


if __name__ == "__main__":
    raise SystemExit(main())

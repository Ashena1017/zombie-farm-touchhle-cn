#!/usr/bin/env python3
"""List every site that can send the `incrementCount:` selector.

Finds the `__objc_methname` address of "incrementCount:", the `__objc_selrefs`
slots that point at it, and then every PC-relative load of those slots in
`__text` (both slices), annotated with the owning method where possible.

Usage: xref_selector.py incrementCount: [--ipa NAME] [--sub 6|9]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import (EXECUTABLE, ROOT, all_methods,  # noqa: E402
                             classes_by_name, u32)


def name_addr(sl, idx, addr):
    a = addr & ~1
    if a in idx:
        n, s, k = idx[a]
        return f'{n} {s}'
    prev = max((x for x in idx if x <= a), default=None)
    if prev is not None and a - prev < 0x1000:
        n, s, k = idx[prev]
        return f'{n} {s} +{a - prev:#x}'
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('selector')
    ap.add_argument('--ipa', default='Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa')
    ap.add_argument('--sub', type=int, default=None)
    a = ap.parse_args()
    want = a.selector.encode() + b'\0'

    with zipfile.ZipFile(ROOT / a.ipa) as z:
        fat = z.read(EXECUTABLE)
    for sl in parse_fat(fat):
        if a.sub is not None and sl.subtype != a.sub:
            continue
        thumb = sl.subtype == 9
        print(f'\n===== sub{sl.subtype} thumb={thumb} =====')

        meth = next(s for s in sl.sections if s.name == '__objc_methname')
        # Every occurrence of the selector name in __objc_methname.
        names = []
        blob = sl.data[meth.offset:meth.offset + meth.size]
        start = 0
        while True:
            i = blob.find(want, start)
            if i < 0:
                break
            names.append(meth.addr + i)
            start = i + 1
        print(f'  __objc_methname occurrence(s): {[hex(x) for x in names]}')

        selrefs = next((s for s in sl.sections if s.name == '__objc_selrefs'), None)
        slots = []
        if selrefs is not None:
            for off in range(0, selrefs.size, 4):
                v = u32(sl, selrefs.addr + off)
                if v in names:
                    slots.append(selrefs.addr + off)
        print(f'  __objc_selrefs slot(s): {[hex(x) for x in slots]}')

        idx = {}
        for name, (cls, info) in classes_by_name(sl).items():
            for m in all_methods(sl, cls, info):
                if m.imp:
                    idx.setdefault(m.imp & ~1, (name, m.selector, m.kind))

        txt = next(s for s in sl.sections if s.name == '__text')
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        md.skipdata = True
        base = txt.addr + (4 if thumb else 8)
        hits = 0
        for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
            if not ins.id:
                continue
            m = ins.mnemonic.split('.')[0]
            ops = ins.operands
            lit = None
            # ARMv7 PIC usually materialises the address with `add rX, pc, #imm`
            # (or a literal pool load); both forms have to be handled.
            if m in ('add', 'adds') and len(ops) >= 2 and ops[1].type == ARM_OP_REG \
                    and ops[1].reg == ARM_REG_PC:
                if len(ops) == 2 and ops[0].type == ARM_OP_REG:
                    lit = ins.address + 4                      # Thumb `add rX, pc`
                elif len(ops) == 3 and ops[2].type == ARM_OP_IMM:
                    lit = (ins.address + 8 + ops[2].imm) & 0xFFFFFFFF
            elif m == 'ldr' and len(ops) == 2 and ops[1].type == ARM_OP_MEM \
                    and ops[1].mem.base == ARM_REG_PC and not ops[1].mem.index:
                lit = ((base + ops[1].mem.disp) & ~3) if thumb \
                    else (ins.address + 8 + ops[1].mem.disp)
            if lit is not None and lit in slots:
                hits += 1
                print(f'   {ins.address:#08x} {ins.mnemonic:<5} {ins.op_str:<30} slot {lit:#x} <- {name_addr(sl, idx, ins.address)}')
        print(f'  {hits} reference(s) to the selector slots')


if __name__ == '__main__':
    main()

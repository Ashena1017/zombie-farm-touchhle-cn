#!/usr/bin/env python3
"""Annotated disassembler: resolves objc selrefs/classrefs/cfstrings and names
branch targets by ObjC method, for either slice of any IPA in the lineage.

Usage:
  annot_disasm.py at ADDR LEN [--ipa N] [--sub 6|9] [--force arm|thumb]
  annot_disasm.py meth CLASS SELECTOR [--ipa N] [--sub 6|9]
  annot_disasm.py xref LO HI [--ipa N] [--sub 6|9]     # all branches into [LO,HI)
"""
from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,
                                ARM_REG_PC, ARM_REG_R0, ARM_REG_R1, ARM_REG_R2,
                                ARM_REG_R3, ARM_REG_R12)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import (  # noqa: E402
    DEFAULT_IPA, EXECUTABLE, ROOT, all_methods, ascii_str, classes_by_name, u32,
)

OBJC = {6: 0x393FE0, 9: 0x2D014C}


def sec_of(sl, addr):
    for s in sl.sections:
        if s.addr <= addr < s.addr + s.size:
            return s.name
    return None


def method_index(sl):
    idx = {}
    for name, (cls, info) in classes_by_name(sl).items():
        for m in all_methods(sl, cls, info):
            if m.imp:
                idx.setdefault(m.imp & ~1, (name, m.selector, m.kind))
    return idx


def name_addr(sl, idx, addr):
    a = addr & ~1
    if a in idx:
        n, s, k = idx[a]
        return f'{n} {s}'
    # nearest preceding method start
    prev = max((x for x in idx if x <= a), default=None)
    if prev is not None and a - prev < 0x1000:
        n, s, k = idx[prev]
        return f'{n} {s} +{a - prev:#x}'
    return ''


def pcbase(addr, thumb):
    b = addr + (4 if thumb else 8)
    return (b & ~3) if thumb else b


def annotate(sl, ins, thumb, idx, regs):
    """Return an annotation string for this instruction."""
    notes = []
    m = ins.mnemonic.split('.', 1)[0]
    ops = ins.operands
    # track ldr rX, [pc, #imm]  and  ldr rX, [pc, rY]
    if m == 'ldr' and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
        mem = ops[1].mem
        if mem.base == ARM_REG_PC:
            if mem.index:
                iv = regs.get(mem.index)
                addr = None if iv is None else pcbase(ins.address, thumb) + mem.disp + iv
            else:
                addr = pcbase(ins.address, thumb) + mem.disp
            if addr is not None:
                w = u32(sl, addr)
                regs[ops[0].reg] = w
                sn = sec_of(sl, addr)
                notes.append(f'[{addr:#x} in {sn}] = {w:#x}' if w is not None else f'[{addr:#x}]')
                if w is not None:
                    tgt_sec = sec_of(sl, w)
                    txt = ascii_str(sl, w)
                    if tgt_sec in ('__objc_methname', '__cstring') and txt:
                        notes.append(f'SEL/STR "{txt}"')
                    elif tgt_sec == '__objc_selrefs':
                        inner = u32(sl, w)
                        notes.append(f'selref-> "{ascii_str(sl, inner)}"')
                    elif tgt_sec == '__objc_classrefs':
                        notes.append('classref slot (dyld-bound)')
                    elif tgt_sec == '__objc_data':
                        ro = u32(sl, w + 16)
                        nm = ascii_str(sl, u32(sl, ro + 16)) if ro else None
                        notes.append(f'class {nm}')
                    elif tgt_sec == '__cfstring':
                        sp = u32(sl, w + 8)
                        notes.append(f'CFSTR "{ascii_str(sl, sp)}"')
            return ' ; '.join(notes)
        elif mem.base in regs and not mem.index:
            # ldr rX, [rY {,#imm}] where rY holds a known absolute address
            a = regs[mem.base] + mem.disp
            w = u32(sl, a)
            if w is None:
                regs.pop(ops[0].reg, None)
            else:
                regs[ops[0].reg] = w
                sn = sec_of(sl, a)
                notes.append(f'[{a:#x} in {sn}] = {w:#x}')
                if sn == '__objc_selrefs':
                    notes.append(f'SEL "{ascii_str(sl, w)}"')
            return ' ; '.join(notes)
        else:
            regs.pop(ops[0].reg, None)
    elif m in ('mov', 'movs', 'movw') and len(ops) == 2:
        if ops[1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ops[1].imm
        elif ops[1].type == ARM_OP_REG:
            v = regs.get(ops[1].reg)
            if v is None:
                regs.pop(ops[0].reg, None)
            else:
                regs[ops[0].reg] = v
        else:
            regs.pop(ops[0].reg, None)
    elif m == 'movt' and len(ops) == 2 and ops[1].type == ARM_OP_IMM:
        regs[ops[0].reg] = ((regs.get(ops[0].reg) or 0) & 0xFFFF) | (ops[1].imm << 16)
    elif m in ('add', 'adds') and len(ops) == 2 and ops[1].type == ARM_OP_REG \
            and ops[1].reg == ARM_REG_PC:
        # Thumb 2-operand "add rX, pc": PC reads as addr+4 (NOT word-aligned)
        v = regs.get(ops[0].reg)
        if v is None:
            return ''
        a = (ins.address + 4 + v) & 0xFFFFFFFF
        regs[ops[0].reg] = a
        sn = sec_of(sl, a)
        notes.append(f'pc-rel {a:#x} in {sn}')
        if sn == '__cfstring':
            notes.append(f'CFSTR "{ascii_str(sl, u32(sl, a + 8))}"')
        elif sn == '__objc_data':
            ro = u32(sl, a + 16)
            notes.append(f'class {ascii_str(sl, u32(sl, ro + 16)) if ro else None}')
        elif sn == '__objc_selrefs':
            notes.append(f'selref-> "{ascii_str(sl, u32(sl, a) or 0)}"')
        elif sn == '__objc_classrefs':
            w = u32(sl, a)
            ro = u32(sl, w + 16) if w else None
            notes.append(f'classref -> {ascii_str(sl, u32(sl, ro + 16)) if ro else "dyld-bound"}')
        elif sn in ('__objc_methname', '__cstring'):
            notes.append(f'STR "{ascii_str(sl, a)}"')
        return ' ; '.join(notes)
    elif m in ('add', 'adds') and len(ops) == 3 and ops[1].type == ARM_OP_REG \
            and ops[1].reg == ARM_REG_PC and ops[2].type == ARM_OP_REG:
        v = regs.get(ops[2].reg)
        if v is not None:
            a = pcbase(ins.address, thumb) + v
            regs[ops[0].reg] = a
            sn = sec_of(sl, a)
            notes.append(f'pc-rel {a:#x} in {sn}')
            if sn == '__cfstring':
                notes.append(f'CFSTR "{ascii_str(sl, u32(sl, a + 8))}"')
            elif sn == '__objc_data':
                ro = u32(sl, a + 16)
                notes.append(f'class {ascii_str(sl, u32(sl, ro + 16)) if ro else None}')
            return ' ; '.join(notes)
    elif m in ('bl', 'blx', 'b') and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm
        if t == OBJC[sl.subtype]:
            sel = regs.get(ARM_REG_R1)
            selname = None
            if sel is not None:
                selname = ascii_str(sl, sel) or ascii_str(sl, u32(sl, sel) or 0)
            notes.append(f'objc_msgSend  sel={selname!r}')
        else:
            nm = name_addr(sl, idx, t)
            sn = sec_of(sl, t)
            notes.append(f'-> {t:#x} {sn or ""} {nm}')
        if m != 'b':
            for r in (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12):
                regs.pop(r, None)
    return ' ; '.join(notes)


def dump(sl, start, length, thumb, idx):
    off = sl.addr_to_file(start)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    regs = {}
    for ins in md.disasm(sl.data[off:off + length], start):
        note = annotate(sl, ins, thumb, idx, regs) if ins.id else ''
        print(f'   {ins.address:#08x}: {ins.bytes.hex():<8} {ins.mnemonic:<11} {ins.op_str:<34} {note}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['at', 'meth', 'xref'])
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--ipa', default=DEFAULT_IPA)
    ap.add_argument('--sub', type=int, default=None)
    ap.add_argument('--force', default=None)
    a = ap.parse_args()
    with zipfile.ZipFile(ROOT / a.ipa) as z:
        fat = z.read(EXECUTABLE)
    for sl in parse_fat(fat):
        if a.sub is not None and sl.subtype != a.sub:
            continue
        thumb = sl.subtype == 9
        if a.force:
            thumb = a.force == 'thumb'
        print(f'\n===== {a.ipa} slice sub{sl.subtype} thumb={thumb} =====')
        idx = method_index(sl)
        if a.cmd == 'at':
            dump(sl, int(a.rest[0], 0), int(a.rest[1], 0), thumb, idx)
        elif a.cmd == 'meth':
            cls, info = classes_by_name(sl)[a.rest[0]]
            starts = sorted(idx)
            for mm in all_methods(sl, cls, info):
                if mm.selector != a.rest[1]:
                    continue
                s = mm.imp & ~1
                e = next((x for x in starts if x > s), s + 0x400)
                print(f'-- {a.rest[0]} {a.rest[1]} imp={mm.imp:#x} {s:#x}..{e:#x}')
                dump(sl, s, min(e - s, 0x900), bool(mm.imp & 1), idx)
        elif a.cmd == 'xref':
            lo, hi = int(a.rest[0], 0), int(a.rest[1], 0)
            txt = next(s for s in sl.sections if s.name == '__text')
            md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
            md.detail = True
            md.skipdata = True
            hits = []
            for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
                if not ins.id or ins.mnemonic.split('.')[0] not in ('bl', 'blx', 'b'):
                    continue
                o = ins.operands
                if o and o[0].type == ARM_OP_IMM and lo <= o[0].imm < hi:
                    hits.append((ins.address, ins.mnemonic, o[0].imm))
            for at, mn, t in hits:
                src = name_addr(sl, idx, at)
                inside = lo <= at < hi
                print(f'   {at:#08x} {mn:<4} -> {t:#08x}   from {src}{"   [INSIDE CAVE]" if inside else ""}')
            print(f'   {len(hits)} branch(es) into {lo:#x}..{hi:#x}')


if __name__ == '__main__':
    main()

"""Selector/stub resolution + tiny dataflow tracker. Read-only."""
import struct
import zipfile
import os
import zt
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_OP_FP,
                                ARM_REG_PC, ARM_REG_SP)
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import EXECUTABLE, ROOT, classes_by_name, all_methods

LC_SEGMENT, LC_SYMTAB, LC_DYSYMTAB = 0x1, 0x2, 0xB


def load_ipa(name):
    with zipfile.ZipFile(os.path.join(str(ROOT), name)) as z:
        fat = z.read(EXECUTABLE)
    return {sl.subtype: sl for sl in parse_fat(fat)}


def sections_full(sl):
    """sections incl. flags/reserved1/reserved2 (audit_zfr_ipa drops them)."""
    out = []
    _, _, _, _, ncmds, _, _ = struct.unpack_from('<IiiIIII', sl.data, 0)
    co = 28
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', sl.data, co)
        if cmd == LC_SEGMENT:
            nsects = struct.unpack_from('<I', sl.data, co + 48)[0]
            so = co + 56
            for _j in range(nsects):
                (nm, sg, addr, size, off, align, reloff, nreloc,
                 flags, r1, r2) = struct.unpack_from('<16s16sIIIIIIIII', sl.data, so)
                out.append(dict(name=nm.split(b'\0')[0].decode(), addr=addr, size=size,
                                off=off, flags=flags, r1=r1, r2=r2))
                so += 68
        co += cmdsize
    return out


def symtab(sl):
    _, _, _, _, ncmds, _, _ = struct.unpack_from('<IiiIIII', sl.data, 0)
    co = 28
    st = dy = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', sl.data, co)
        if cmd == LC_SYMTAB:
            st = struct.unpack_from('<IIII', sl.data, co + 8)
        elif cmd == LC_DYSYMTAB:
            dy = struct.unpack_from('<' + 'I' * 18, sl.data, co + 8)
        co += cmdsize
    return st, dy


def stub_map(sl):
    """addr of each __symbol_stub4 entry -> imported symbol name."""
    secs = sections_full(sl)
    st, dy = symtab(sl)
    if not st or not dy:
        return {}
    symoff, nsyms, stroff, strsize = st
    indirectsymoff, nindirectsyms = dy[12], dy[13]
    strings = sl.data[stroff:stroff + strsize]

    def symname(idx):
        n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from(
            '<IBBHI', sl.data, symoff + 12 * idx)
        e = strings.find(b'\0', n_strx)
        return strings[n_strx:e].decode('utf-8', 'replace')

    out = {}
    for s in secs:
        if s['name'] not in ('__symbol_stub4', '__la_symbol_ptr', '__nl_symbol_ptr'):
            continue
        stride = s['r2'] if s['name'] == '__symbol_stub4' and s['r2'] else 4
        if stride <= 0:
            stride = 4
        cnt = s['size'] // stride
        for i in range(cnt):
            ii = s['r1'] + i
            if ii >= nindirectsyms:
                break
            symidx = struct.unpack_from('<I', sl.data, indirectsymoff + 4 * ii)[0]
            if symidx in (0x40000000, 0x80000000, 0xC0000000):
                continue
            try:
                out[s['addr'] + i * stride] = symname(symidx)
            except Exception:
                pass
    return out


def selref_map(sl):
    """__objc_selrefs slot addr -> selector text."""
    out = {}
    for s in sl.sections:
        if s.name != '__objc_selrefs':
            continue
        for i in range(s.size // 4):
            a = s.addr + i * 4
            p = struct.unpack_from('<I', sl.data, s.offset + i * 4)[0]
            t = sl.cstr(p)
            if not t.startswith('<addr'):
                out[a] = t
    return out


def classref_map(sl):
    out = {}
    from inspect_v3_facts import class_ro
    for s in sl.sections:
        if s.name != '__objc_classrefs':
            continue
        for i in range(s.size // 4):
            a = s.addr + i * 4
            p = struct.unpack_from('<I', sl.data, s.offset + i * 4)[0]
            if not p:
                continue
            info = class_ro(sl, p)
            if info and info['name']:
                out[a] = info['name']
    return out


def owner_map(sl):
    """sorted list of (imp_start, class, kind, selector) for attribution."""
    rows = []
    for cn, (cls, info) in classes_by_name(sl).items():
        for m in all_methods(sl, cls, info):
            if m.imp:
                rows.append((m.imp & ~1, cn, m.kind, m.selector))
    rows.sort()
    return rows


def owner_of(rows, addr):
    import bisect
    i = bisect.bisect_right(rows, (addr, chr(0x10FFFF), '', '')) - 1
    return rows[i] if i >= 0 else None

#!/usr/bin/env python3
"""Reusable inspector for the v3 font work: ObjC class/ivar/method layout plus
targeted disassembly, for any IPA in the lineage.

Subcommands
  ivars   CLASS...          ivar layout (correct class_ro_t: ivars at +28)
  meths   CLASS...          full instance+class method lists
  disasm  CLASS SELECTOR    disassemble one method
  at      ADDR LEN          disassemble an arbitrary address range
  selrefs SUBSTRING         every selector string containing SUBSTRING
"""
from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import Method, parse_fat  # noqa: E402

EXECUTABLE = 'Payload/ZFR.app/ZFR'
ROOT = Path(__file__).resolve().parent.parent / 'zombie_farm_ipa'
DEFAULT_IPA = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed.ipa'


def u32(sl, addr):
    off = sl.addr_to_file(addr)
    if off is None or off + 4 > len(sl.data):
        return None
    return struct.unpack_from('<I', sl.data, off)[0]


def ascii_str(sl, addr):
    if not addr:
        return None
    s = sl.cstr(addr)
    if s.startswith('<addr '):
        return None
    return s.encode('ascii', 'backslashreplace').decode('ascii')


def iter_classlist(sl):
    for s in sl.sections:
        if s.name != '__objc_classlist':
            continue
        for i in range(s.size // 4):
            yield struct.unpack_from('<I', sl.data, s.offset + i * 4)[0]


def class_ro(sl, cls):
    """class_ro_t: flags,instStart,instSize,ivarLayout,name,methods,protos,ivars,..."""
    ro = u32(sl, cls + 16)
    if not ro:
        return None
    return {
        'ro': ro,
        'instance_size': u32(sl, ro + 8),
        'name': ascii_str(sl, u32(sl, ro + 16)),
        'methods': u32(sl, ro + 20),
        'ivars': u32(sl, ro + 28),
        'props': u32(sl, ro + 36),
    }


def classes_by_name(sl):
    out = {}
    for cls in iter_classlist(sl):
        info = class_ro(sl, cls)
        if info and info['name']:
            out[info['name']] = (cls, info)
    return out


def read_ivars(sl, ivars_addr):
    if not ivars_addr:
        return []
    off = sl.addr_to_file(ivars_addr)
    if off is None or off + 8 > len(sl.data):
        return []
    entsize, count = struct.unpack_from('<II', sl.data, off)
    if not (12 <= entsize <= 64) or count > 4096:
        return []
    out = []
    for i in range(count):
        e = off + 8 + i * entsize
        if e + 20 > len(sl.data):
            break
        off_ptr, name_ptr, type_ptr, align, size = struct.unpack_from('<IIIII', sl.data, e)
        out.append({
            'offset': u32(sl, off_ptr) if off_ptr else None,
            'name': ascii_str(sl, name_ptr),
            'type': ascii_str(sl, type_ptr),
            'size': size,
        })
    return out


def read_methods(sl, list_addr, cls_name, kind):
    if not list_addr:
        return []
    off = sl.addr_to_file(list_addr)
    if off is None or off + 8 > len(sl.data):
        return []
    entsize, count = struct.unpack_from('<II', sl.data, off)
    if not (12 <= entsize <= 64) or count > 8192:
        return []
    out = []
    for i in range(count):
        e = off + 8 + i * entsize
        if e + 12 > len(sl.data):
            break
        name_ptr, types_ptr, imp = struct.unpack_from('<III', sl.data, e)
        out.append(Method(cls_name, kind, ascii_str(sl, name_ptr) or '?',
                          ascii_str(sl, types_ptr) or '?', imp, sl.addr_to_file(imp)))
    return out


def all_methods(sl, cls, info):
    """Instance methods plus metaclass (class) methods, with the ivar-correct ro."""
    out = read_methods(sl, info['methods'], info['name'], 'instance')
    meta = u32(sl, cls)
    if meta:
        minfo = class_ro(sl, meta)
        if minfo:
            out += read_methods(sl, minfo['methods'], info['name'], 'class')
    return out


def method_starts(sl):
    starts = set()
    for cls in iter_classlist(sl):
        info = class_ro(sl, cls)
        if not info:
            continue
        for m in all_methods(sl, cls, info):
            if m.imp:
                starts.add(m.imp & ~1)
    return sorted(starts)


def disasm_range(sl, start, length, thumb, label=''):
    off = sl.addr_to_file(start)
    if off is None:
        print(f'   {label}{start:#x}: not file-backed')
        return
    code = sl.data[off:off + length]
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.skipdata = True
    md.detail = False
    for ins in md.disasm(code, start):
        print(f'   {ins.address:#08x}: {ins.bytes.hex():<8} {ins.mnemonic:<10} {ins.op_str}')
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['ivars', 'meths', 'disasm', 'at', 'selrefs'])
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--ipa', default=DEFAULT_IPA)
    ap.add_argument('--sub', type=int, default=None,
                    help='restrict to CPU subtype 6 (ARMv6) or 9 (ARMv7)')
    args = ap.parse_args()

    with zipfile.ZipFile(ROOT / args.ipa) as z:
        fat = z.read(EXECUTABLE)

    for sl in parse_fat(fat):
        if args.sub is not None and sl.subtype != args.sub:
            continue
        thumb = sl.subtype == 9
        print(f'\n========== slice subtype={sl.subtype} thumb={thumb} ==========')
        byname = classes_by_name(sl)

        if args.cmd == 'ivars':
            for want in args.rest:
                if want not in byname:
                    print(f'-- {want}: NOT FOUND'); continue
                cls, info = byname[want]
                sup = u32(sl, cls + 4)
                sup_info = class_ro(sl, sup) if sup else None
                print(f'-- {want} cls={cls:#x} instance_size={info["instance_size"]} '
                      f'super={sup_info["name"] if sup_info else None}')
                for iv in read_ivars(sl, info['ivars']):
                    mark = ' <<<<' if iv['offset'] in (0xD0, 0xD4, 0xD8, 0xDC, 0x190) else ''
                    o = iv['offset']
                    print(f'   +{o:#05x} ({o:>4}) {iv["name"]:<26} {iv["type"]:<14} sz={iv["size"]}{mark}')

        elif args.cmd == 'meths':
            for want in args.rest:
                if want not in byname:
                    print(f'-- {want}: NOT FOUND'); continue
                cls, info = byname[want]
                print(f'-- {want} cls={cls:#x}')
                for m in sorted(all_methods(sl, cls, info), key=lambda m: m.selector):
                    print(f'   [{m.kind:<8}] {m.selector:<58} types={m.types:<16} imp={m.imp:#x}')

        elif args.cmd == 'disasm':
            want, sel = args.rest[0], args.rest[1]
            cls, info = byname[want]
            starts = method_starts(sl)
            for m in all_methods(sl, cls, info):
                if m.selector != sel:
                    continue
                start = m.imp & ~1
                end = next((s for s in starts if s > start), start + 0x400)
                print(f'-- {want} [{m.kind}] {sel} imp={m.imp:#x} range={start:#x}..{end:#x}')
                disasm_range(sl, start, min(end - start, 0x800), bool(m.imp & 1))

        elif args.cmd == 'at':
            addr = int(args.rest[0], 0)
            length = int(args.rest[1], 0) if len(args.rest) > 1 else 0x40
            force = args.rest[2] if len(args.rest) > 2 else None
            t = thumb if force is None else (force == 'thumb')
            print(f'-- {addr:#x}..{addr+length:#x} thumb={t}')
            disasm_range(sl, addr, length, t)

        elif args.cmd == 'selrefs':
            needle = args.rest[0]
            seen = set()
            for s in sl.sections:
                if s.name not in ('__cstring', '__objc_methname'):
                    continue
                blob = sl.data[s.offset:s.offset + s.size]
                pos = 0
                while True:
                    k = blob.find(needle.encode(), pos)
                    if k < 0:
                        break
                    lo = blob.rfind(b'\0', 0, k) + 1
                    hi = blob.find(b'\0', k)
                    txt = blob[lo:hi].decode('ascii', 'backslashreplace')
                    addr = s.addr + lo
                    if txt not in seen:
                        seen.add(txt)
                        print(f'   {addr:#x} {s.name}: {txt}')
                    pos = hi + 1 if hi > 0 else k + 1


if __name__ == '__main__':
    main()


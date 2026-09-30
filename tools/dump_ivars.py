#!/usr/bin/env python3
"""Dump ObjC ivar layouts for ZFAlertWindow / CCLabel-ish classes.

Confirms the ivar offsets the v2/v3 wrappers hard-code:
  ZFAlertWindow title1/body1/body2 at +0xd0/+0xd4/+0xd8
  label fontSize_ at +0x190
"""
from __future__ import annotations
import struct, sys, zipfile
from pathlib import Path
from audit_zfr_ipa import parse_fat

EXECUTABLE = 'Payload/ZFR.app/ZFR'
WANT = {'ZFAlertWindow', 'CCLabel', 'CCLabelTTF', 'CCLabelAtlas', 'CCLabelBMFont',
        'CCSprite', 'CCNode', 'ZFLabel', 'ZFButton'}


def u32(sl, addr):
    off = sl.addr_to_file(addr)
    if off is None or off + 4 > len(sl.data):
        return None
    return struct.unpack_from('<I', sl.data, off)[0]


def classes(sl):
    """Walk __objc_classlist."""
    out = []
    for s in sl.sections:
        if s.name != '__objc_classlist':
            continue
        n = s.size // 4
        for i in range(n):
            cls = struct.unpack_from('<I', sl.data, s.offset + i * 4)[0]
            out.append(cls)
    return out


def class_info(sl, cls):
    ro = u32(sl, cls + 16)
    if ro is None:
        return None
    name_ptr = u32(sl, ro + 16)
    name = sl.cstr(name_ptr) if name_ptr else '?'
    ivars = u32(sl, ro + 24)
    instance_size = u32(sl, ro + 8)
    superclass = u32(sl, cls + 4)
    return {'name': name, 'ivars': ivars, 'size': instance_size, 'super': superclass, 'ro': ro}


def dump_ivars(sl, ivar_list):
    if not ivar_list:
        return []
    off = sl.addr_to_file(ivar_list)
    if off is None or off + 8 > len(sl.data):
        return []
    entsize, count = struct.unpack_from('<II', sl.data, off)
    if entsize < 20 or entsize > 64 or count > 4096:
        return []
    out = []
    for i in range(count):
        e = off + 8 + i * entsize
        if e + 20 > len(sl.data):
            break
        off_ptr, name_ptr, type_ptr, alignment, size = struct.unpack_from('<IIIII', sl.data, e)
        ivar_off = u32(sl, off_ptr) if off_ptr else None
        out.append((ivar_off, sl.cstr(name_ptr), sl.cstr(type_ptr), size))
    return out


def main():
    ipa = Path(sys.argv[1])
    with zipfile.ZipFile(ipa) as z:
        fat = z.read(EXECUTABLE)
    for si, sl in enumerate(parse_fat(fat)):
        print(f'===== slice {si} subtype={sl.subtype} =====')
        by_name = {}
        for cls in classes(sl):
            info = class_info(sl, cls)
            if info:
                by_name[info['name']] = (cls, info)
        for name in sorted(by_name):
            if name not in WANT:
                continue
            cls, info = by_name[name]
            print(f'-- {name} cls={cls:#x} instance_size={info["size"]}')
            for ivar_off, iname, itype, isize in dump_ivars(sl, info['ivars']):
                mark = ''
                if ivar_off in (0xd0, 0xd4, 0xd8, 0xdc, 0x190):
                    mark = '   <<<<'
                print(f'   +{ivar_off:#05x} {iname:<28} {itype:<12} size={isize}{mark}')
        # Find whatever class owns a fontSize_ ivar at 0x190
        print('-- classes with an ivar named fontSize_ / fontSize:')
        for name, (cls, info) in sorted(by_name.items()):
            pass
        for cls in classes(sl):
            info = class_info(sl, cls)
            if not info:
                continue
            for ivar_off, iname, itype, isize in dump_ivars(sl, info['ivars']):
                if iname and 'ontSize' in iname:
                    print(f'   {info["name"]}: +{ivar_off:#x} {iname} {itype}')
        print()


if __name__ == '__main__':
    main()

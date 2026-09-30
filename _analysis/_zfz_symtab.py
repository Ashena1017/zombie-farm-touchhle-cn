#!/usr/bin/env python3
"""Parse LC_DYSYMTAB indirect symbol tables so __symbol_stub4 / __nl_symbol_ptr
slots can be mapped to symbol names.

Usage: python _analysis/_zfz_symtab.py 0x2cf9e4 [more stubs]
"""
from __future__ import annotations

import pathlib as _pl
import struct
import sys
import zipfile

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

# locate the sub9 slice offset inside the FAT
n = struct.unpack_from(">I", fat, 4)[0]
sub9_off = None
for i in range(n):
    cpu, sub, off, size, align = struct.unpack_from(">IIIII", fat, 8 + i * 20)
    if sub == 9:
        sub9_off = off
assert sub9_off is not None
macho = fat[sub9_off:]

magic, cputype, cpusub, filetype, ncmds, sizeofcmds, flags = struct.unpack_from("<7I", macho, 0)
print("mach-o magic=%#x ncmds=%d sizeofcmds=%#x" % (magic, ncmds, sizeofcmds))

# sections
sections = {}
symtab = None
dysymtab = None
p = 28
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack_from("<II", macho, p)
    if cmd == 1:  # LC_SEGMENT
        nsects = struct.unpack_from("<I", macho, p + 48)[0]
        q = p + 56
        for _s in range(nsects):
            name = macho[q:q + 16].split(b"\0")[0].decode()
            addr, size, off, align, reloff, nreloc, fl, r1, r2 = struct.unpack_from("<9I", macho, q + 16)
            sections[name] = dict(addr=addr, size=size, off=off, flags=fl, reserved1=r1, reserved2=r2)
            q += 68
    elif cmd == 0x2:  # LC_SYMTAB
        symtab = struct.unpack_from("<6I", macho, p + 8)
    elif cmd == 0xB:  # LC_DYSYMTAB
        dysymtab = struct.unpack_from("<18I", macho, p + 8)
    p += cmdsize

print("sections: %s" % sorted(sections))
print("symtab: %s" % (symtab,))
print("dysymtab: %s" % (dysymtab,))

symoff, nsyms, stroff, strsize = symtab[:4]
ilocalsym, nlocalsym, iextdefsym, nextdefsym, iundefsym, nundefsym = dysymtab[:6]
indirectoff, nindirect = dysymtab[12], dysymtab[13]


def symname(i):
    o = symoff + i * 12
    strx = struct.unpack_from("<I", macho, o)[0]
    s = macho[stroff + strx:macho.index(b"\0", stroff + strx)]
    return s.decode("utf-8", "replace")


# indirect symbol table entries
ind = list(struct.unpack_from("<%dI" % nindirect, macho, indirectoff))

for a in sys.argv[1:]:
    addr = int(a, 0)
    sec = None
    for name, s in sections.items():
        if s["addr"] <= addr < s["addr"] + s["size"]:
            sec = (name, s)
    print("\n%#x in section %s" % (addr, sec[0] if sec else None))
    if not sec:
        continue
    name, s = sec
    idx = (addr - s["addr"]) // 4          # stub slots are 12 bytes; ptr slots 4
    if name == "__symbol_stub4":
        idx = (addr - s["addr"]) // 12
        print("   stub index %d -> indirect[%d] = %d"
              % (idx, s["reserved2"] + idx, ind[s["reserved2"] + idx]))
        si = ind[s["reserved2"] + idx]
        if si & 0x40000000:
            print("   LOCAL/ABS flag")
        else:
            print("   symbol = %r" % symname(si))
    else:
        si = ind[s["reserved2"] + idx]
        print("   ptr index %d -> indirect[%d] = %d -> %r"
              % (idx, s["reserved2"] + idx, si, symname(si) if not (si & 0x40000000) else "?"))

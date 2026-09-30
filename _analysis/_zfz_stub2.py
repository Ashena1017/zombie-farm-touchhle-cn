#!/usr/bin/env python3
"""Resolve a Thumb __symbol_stub4 stub to its imported symbol name by reading the
pointer word inside the stub, then mapping that __la/__nl_symbol_ptr slot through
LC_DYSYMTAB's indirect symbol table.

Usage: python _analysis/_zfz_stub2.py 0x2d014c [more]
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
    sl = next(s for s in parse_fat(fat) if s.subtype == 9)

n = struct.unpack_from(">I", fat, 4)[0]
for i in range(n):
    cpu, sub, off, size, al = struct.unpack_from(">IIIII", fat, 8 + i * 20)
    if sub == 9:
        sub9 = off
m = fat[sub9:]

symtab = dysym = None
p = 28
for _ in range(struct.unpack_from("<I", m, 16)[0]):
    cmd, cs = struct.unpack_from("<II", m, p)
    if cmd == 0x2:
        symtab = struct.unpack_from("<6I", m, p + 8)
    elif cmd == 0xB:
        dysym = struct.unpack_from("<18I", m, p + 8)
    p += cs
symoff, nsyms, stroff, strsize = symtab[:4]
indirectoff, nindirect = dysym[12], dysym[13]
ind = list(struct.unpack_from("<%dI" % nindirect, m, indirectoff))


def symname(i):
    o = symoff + i * 12
    strx = struct.unpack_from("<I", m, o)[0]
    e = m.index(b"\0", stroff + strx)
    return m[stroff + strx:e].decode("utf-8", "replace")


raw = {}
p = 28
for _ in range(struct.unpack_from("<I", m, 16)[0]):
    cmd, cs = struct.unpack_from("<II", m, p)
    if cmd == 1:
        nsects = struct.unpack_from("<I", m, p + 48)[0]
        q = p + 56
        for _s in range(nsects):
            nm = m[q:q + 16].split(b"\0")[0].decode()
            addr, size, off, align, reloff, nreloc, fl, r1, r2 = \
                struct.unpack_from("<9I", m, q + 32)
            raw[nm] = dict(addr=addr, size=size, off=off, flags=fl, r1=r1, r2=r2)
            q += 68
    p += cs


def ptr_slot_name(word):
    """word is a VM address inside a pointer section -> symbol name."""
    for nm in ("__la_symbol_ptr", "__nl_symbol_ptr"):
        r = raw[nm]
        if r["addr"] <= word < r["addr"] + r["size"]:
            idx = (word - r["addr"]) // 4
            si = ind[r["r1"] + idx]
            return nm, idx, (symname(si) if si < nsyms else "?")
    return None, None, None


for a in sys.argv[1:]:
    addr = int(a, 0)
    o = sl.addr_to_file(addr)
    b = sl.data[o:o + 12]
    w = struct.unpack_from("<I", b, 8)[0] if len(b) >= 12 else None
    nm, idx, sym = ptr_slot_name(w) if w else (None, None, None)
    print("%#x  stub bytes=%s  ptr=%s -> %s[%s] = %r"
          % (addr, b.hex(), hex(w) if w else None, nm, idx, sym))

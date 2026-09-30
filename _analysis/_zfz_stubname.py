#!/usr/bin/env python3
"""Resolve __symbol_stub4 / __la_symbol_ptr / __nl_symbol_ptr slots to symbol names
via LC_DYSYMTAB's indirect symbol table.

Usage: python _analysis/_zfz_stubname.py 0x2cf9e4 [more]
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
n = struct.unpack_from(">I", fat, 4)[0]
sub9 = None
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


with zipfile.ZipFile(IPA) as z:
    sl = next(s for s in parse_fat(z.read("Payload/ZFR.app/ZFR")) if s.subtype == 9)
secs = {s.name: s for s in sl.sections}

# reserved1/reserved2 are not exposed by audit_zfr_ipa.Section -> re-read raw
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
            raw[nm] = dict(addr=addr, size=size, off=off, flags=fl,
                           reserved1=r1, reserved2=r2)
            q += 68
    p += cs

for nm in ("__symbol_stub4", "__la_symbol_ptr", "__nl_symbol_ptr"):
    r = raw.get(nm)
    if r:
        print("%-18s addr=%#x size=%#x reserved1=%d reserved2=%d"
              % (nm, r["addr"], r["size"], r["reserved1"], r["reserved2"]))

for a in sys.argv[1:]:
    addr = int(a, 0)
    hit = False
    # __symbol_stub4 : reserved2 = first indirect index, 12-byte stubs
    # __la_symbol_ptr/__nl_symbol_ptr : reserved1 = first indirect index, 4-byte slots
    for nm, stride, field in (("__symbol_stub4", 12, "reserved2"),
                              ("__la_symbol_ptr", 4, "reserved1"),
                              ("__nl_symbol_ptr", 4, "reserved1")):
        r = raw.get(nm)
        if not r or not (r["addr"] <= addr < r["addr"] + r["size"]):
            continue
        hit = True
        idx = (addr - r["addr"]) // stride
        si = ind[r[field] + idx]
        print("%#x in %-18s idx=%-4d indirect=%-4d symbol=%r"
              % (addr, nm, idx, si, symname(si) if si < nsyms else "?"))
    if not hit:
        print("%#x : not in a stub/ptr section" % addr)

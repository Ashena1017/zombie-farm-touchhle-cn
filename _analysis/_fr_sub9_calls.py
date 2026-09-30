#!/usr/bin/env python3
"""Resolve the symbol stubs called by sub9 CCFastDirector -preMainLoop, so we
know exactly which calls cost time before patching one of them out.

Calls of interest (sub9, armv7 -- the slice touchHLE actually executes):
    0x213abc  blx  <stub>   pre-drawScene  run-loop drain
    0x213ad2  blx  <stub>   guarded call with r0 = 0x3d090 (250000)
    0x213ada  blx  objc_msgSend  sel = drawScene
    0x213ae6  blx  <stub>   post-drawScene run-loop drain
"""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"
SUBTYPE = 9  # armv7

LC_SEGMENT = 0x1
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB


def load_cmds(data):
    ncmds = struct.unpack_from("<I", data, 16)[0]
    out, off = [], 28
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        out.append((cmd, cmdsize, off))
        off += cmdsize
    return out


def sections(data):
    out = []
    for cmd, _cs, off in load_cmds(data):
        if cmd != LC_SEGMENT:
            continue
        nsects = struct.unpack_from("<I", data, off + 48)[0]
        sp = off + 56
        for _ in range(nsects):
            name = data[sp:sp + 16].split(b"\0", 1)[0].decode("ascii", "replace")
            (addr, size, offset, _al, _ro, _nr, _fl, r1, r2) = \
                struct.unpack_from("<9I", data, sp + 32)
            out.append(dict(name=name, addr=addr, size=size, offset=offset, res1=r1))
            sp += 68
    return out


def addr_to_file(data, addr):
    for s in sections(data):
        if s["addr"] <= addr < s["addr"] + s["size"]:
            return s["offset"] + addr - s["addr"]
    return None


def symtab(data):
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_SYMTAB:
            return struct.unpack_from("<IIII", data, off + 8)
    raise SystemExit("no LC_SYMTAB")


def dysymtab(data):
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_DYSYMTAB:
            f = struct.unpack_from("<18I", data, off + 8)
            return f[12], f[13]
    raise SystemExit("no LC_DYSYMTAB")


def sym_name(data, idx):
    symoff, nsyms, stroff, strsize = symtab(data)
    if idx in (0, 0xFFFF, 0xFFFFFF) or idx >= nsyms:
        return "<none>"
    strx = struct.unpack_from("<I", data, symoff + idx * 12)[0]
    if strx >= strsize:
        return "<bad>"
    return data[stroff + strx: stroff + strsize].split(b"\0", 1)[0].decode("utf-8", "replace")


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    sl = next(s for s in parse_fat(fat) if s.subtype == SUBTYPE)
    data = sl.data

    slabs = sections(data)
    # find __symbol_stub4 and the two pointer sections
    stub = next(s for s in slabs if s["name"] == "__symbol_stub4")
    print(f"__symbol_stub4 addr={stub['addr']:#x} size={stub['size']:#x} "
          f"-> {stub['size']//16} stubs")

    ind_off, ind_n = dysymtab(data)
    indirect = struct.unpack_from(f"<{ind_n}I", data, ind_off)
    slot_names = {}
    for s in slabs:
        if s["name"] in ("__la_symbol_ptr", "__nl_symbol_ptr"):
            for k in range(s["size"] // 4):
                i = s["res1"] + k
                if i < len(indirect):
                    slot_names[s["addr"] + k * 4] = sym_name(data, indirect[i])

    def resolve(stub_addr):
        o = addr_to_file(data, stub_addr)
        if o is None:
            return None, None
        hw1, hw2 = struct.unpack_from("<HH", data, o)
        if hw1 == 0xF8DF and (hw2 & 0xF000) == 0xC000:   # ldr.w r12,[pc,#imm]
            lit = ((stub_addr + 4) & ~3) + (hw2 & 0x0FFF)
        else:
            first = struct.unpack_from("<I", data, o)[0]
            if (first & 0xFFFFF000) == 0xE59FC000:       # ldr r12,[pc,#imm]
                lit = stub_addr + 8 + (first & 0xFFF)
            else:
                return None, None
        lo = addr_to_file(data, lit)
        if lo is None:
            return None, None
        slot = struct.unpack_from("<I", data, lo)[0]
        return slot, slot_names.get(slot, "<?>")

    # decode each blx in preMainLoop and report target + resolved symbol
    lo, hi = 0x213A30, 0x213B10
    print(f"\n=== calls in sub9 CCFastDirector -preMainLoop "
          f"({lo:#x}..{hi:#x}) ===")
    off = addr_to_file(data, lo)
    addr = lo
    while addr < hi:
        hw1, hw2 = struct.unpack_from("<HH", data, off)
        # Thumb BL / BLX (32-bit): 11110 S imm10 | 11 J1 1 J2 imm11
        if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xC000) == 0xC000:
            S = (hw1 >> 10) & 1
            imm10 = hw1 & 0x03FF
            J1 = (hw2 >> 13) & 1
            J2 = (hw2 >> 11) & 1
            imm11 = hw2 & 0x07FF
            I1 = (~(J1 ^ S)) & 1
            I2 = (~(J2 ^ S)) & 1
            imm32 = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
            if imm32 & (1 << 24):
                imm32 -= 1 << 25
            target = (addr + 4 + imm32) & 0xFFFFFFFF
            slot, name = resolve(target)
            kind = "BLX" if (hw2 & 0x1000) == 0 else "BL "
            print(f"  {addr:#08x}  {kind} -> {target:#08x}  {name}")
            off += 4
            addr += 4
            continue
        off += 2
        addr += 2


if __name__ == "__main__":
    main()

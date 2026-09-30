#!/usr/bin/env python3
"""Resolve the symbol stub that sub9 CCDirector -calculateDeltaTime calls.

This is the load-bearing proof for "raising the framerate does not speed the
game up":

    -drawScene  ->  -calculateDeltaTime  ->  <this stub>  ->  ?

If <this stub> is gettimeofday (or time), the frame delta is real elapsed
wall-clock time, so drawing twice as often halves each delta rather than
doubling the rate at which game time advances.
"""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"
SUBTYPE = 9                      # armv7 == the slice touchHLE loads
CALC_DT = 0x211A90               # CCDirector -calculateDeltaTime (thumb)

LC_SEGMENT, LC_SYMTAB, LC_DYSYMTAB = 0x1, 0x2, 0xB


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
            (addr, size, offset, _al, _ro, _nr, _fl, r1, _r2) = \
                struct.unpack_from("<9I", data, sp + 32)
            out.append(dict(name=name, addr=addr, size=size, offset=offset, res1=r1))
            sp += 68
    return out


def addr_to_file(data, addr):
    for s in sections(data):
        if s["addr"] <= addr < s["addr"] + s["size"]:
            return s["offset"] + addr - s["addr"]
    return None


def sym_name(data, idx):
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, off + 8)
            break
    else:
        raise SystemExit("no LC_SYMTAB")
    if idx in (0, 0xFFFF, 0xFFFFFF) or idx >= nsyms:
        return "<none>"
    strx = struct.unpack_from("<I", data, symoff + idx * 12)[0]
    if strx >= strsize:
        return "<bad>"
    return data[stroff + strx: stroff + strsize].split(b"\0", 1)[0].decode("utf-8", "replace")


def slot_names(data):
    ind_off = ind_n = None
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_DYSYMTAB:
            f = struct.unpack_from("<18I", data, off + 8)
            ind_off, ind_n = f[12], f[13]
    indirect = struct.unpack_from(f"<{ind_n}I", data, ind_off)
    out = {}
    for s in sections(data):
        if s["name"] in ("__la_symbol_ptr", "__nl_symbol_ptr"):
            for k in range(s["size"] // 4):
                i = s["res1"] + k
                if i < len(indirect):
                    out[s["addr"] + k * 4] = sym_name(data, indirect[i])
    return out


def stub_target(data, stub_addr, names):
    """Resolve a Thumb-2 or ARM symbol stub to (slot_address, symbol_name)."""
    o = addr_to_file(data, stub_addr)
    if o is None:
        return None, None
    hw1, hw2 = struct.unpack_from("<HH", data, o)
    if hw1 == 0xF8DF and (hw2 & 0xF000) == 0xC000:        # Thumb: ldr.w r12,[pc,#imm]
        lit = ((stub_addr + 4) & ~3) + (hw2 & 0x0FFF)
    else:
        first = struct.unpack_from("<I", data, o)[0]
        if (first & 0xFFFFF000) == 0xE59FC000:            # ARM: ldr r12,[pc,#imm]
            lit = stub_addr + 8 + (first & 0xFFF)
        else:
            return None, None
    lo = addr_to_file(data, lit)
    if lo is None:
        return None, None
    slot = struct.unpack_from("<I", data, lo)[0]
    return slot, names.get(slot, "<?>")


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    sl = next(s for s in parse_fat(fat) if s.subtype == SUBTYPE)
    data = sl.data
    names = slot_names(data)

    print(f"=== sub{SUBTYPE} (armv7 -- the slice touchHLE loads) ===")
    print(f"CCDirector -calculateDeltaTime @ {CALC_DT:#x} (thumb)\n")

    off = addr_to_file(data, CALC_DT)
    addr = CALC_DT
    limit = CALC_DT + 0x160
    print("every call in the method, with its resolved symbol:")
    while addr < limit:
        hw1, hw2 = struct.unpack_from("<HH", data, off)
        is_bl = (hw1 & 0xF800) == 0xF000 and (hw2 & 0xC000) == 0xC000
        if is_bl:
            S, imm10 = (hw1 >> 10) & 1, hw1 & 0x03FF
            J1, J2, imm11 = (hw2 >> 13) & 1, (hw2 >> 11) & 1, hw2 & 0x07FF
            I1, I2 = (~(J1 ^ S)) & 1, (~(J2 ^ S)) & 1
            imm32 = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
            if imm32 & (1 << 24):
                imm32 -= 1 << 25
            target = (addr + 4 + imm32) & 0xFFFFFFFF
            slot, name = stub_target(data, target, names)
            if name is None:
                name = "(direct branch)"
            print(f"  {addr:#08x}  target={target:#08x}  {name}")
            off += 4
            addr += 4
            continue
        # pop {..., pc} ends the function
        if hw1 == 0xBDF0 or hw1 == 0xBD00 or (hw1 & 0xFF00) == 0xBD00:
            print(f"  {addr:#08x}  <return>")
            break
        off += 2
        addr += 2

    print("\ninterpretation:")
    print("  gettimeofday / time / CFAbsoluteTimeGetCurrent => dt is real wall-clock")
    print("  time, so a higher framerate only makes each dt smaller.")


if __name__ == "__main__":
    main()

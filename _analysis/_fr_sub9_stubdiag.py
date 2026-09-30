#!/usr/bin/env python3
"""Diagnose the sub9 stub layout so the delta-time call can be named."""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"
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
        segname = data[off + 8:off + 24].split(b"\0", 1)[0].decode()
        nsects = struct.unpack_from("<I", data, off + 48)[0]
        sp = off + 56
        for _ in range(nsects):
            name = data[sp:sp + 16].split(b"\0", 1)[0].decode("ascii", "replace")
            (addr, size, offset, _al, _ro, _nr, _fl, r1, _r2) = \
                struct.unpack_from("<9I", data, sp + 32)
            out.append(dict(seg=segname, name=name, addr=addr, size=size,
                            offset=offset, res1=r1))
            sp += 68
    return out


def addr_to_file(secs, addr):
    for s in secs:
        if s["addr"] <= addr < s["addr"] + s["size"]:
            return s["offset"] + addr - s["addr"]
    return None


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    sl = next(s for s in parse_fat(fat) if s.subtype == 9)
    data = sl.data
    secs = sections(data)

    print("=== sub9 sections mentioning stub/ptr ===")
    for s in secs:
        if any(k in s["name"] for k in ("stub", "symbol_ptr", "picsymbol")):
            print(f"  {s['seg']},{s['name']}  addr={s['addr']:#x} size={s['size']:#x} "
                  f"off={s['offset']:#x} reserved1={s['res1']}")

    for probe in (0x2CF3E4, 0x2D0410, 0x2D0412, 0x2D014E, 0x2D07AC):
        o = addr_to_file(secs, probe)
        if o is None:
            print(f"\n{probe:#x}: not file-backed")
            continue
        b = data[o:o + 16]
        hw = struct.unpack_from("<HH", b, 0)
        hw4 = struct.unpack_from("<I", b, 0)
        print(f"\n{probe:#x} (file {o:#x}): {b.hex()}")
        print(f"   as 2x u16: {hw[0]:#06x} {hw[1]:#06x}   as u32: {hw4[0]:#010x}")
        # thumb ldr.w r12,[pc,#imm]
        if hw[0] == 0xF8DF and (hw[1] & 0xF000) == 0xC000:
            lit = ((probe + 4) & ~3) + (hw[1] & 0x0FFF)
            print(f"   Thumb ldr.w r12,[pc,#{hw[1] & 0x0FFF:#x}] -> literal @ {lit:#x}")
            lo = addr_to_file(secs, lit)
            if lo is not None:
                slot = struct.unpack_from("<I", data, lo)[0]
                print(f"      literal value (slot addr) = {slot:#x}")
        # thumb ldr r12,[pc,#imm]
        if (hw[0] & 0xF800) == 0x4800:
            imm = (hw[0] & 0xFF) * 4
            lit = ((probe + 4) & ~3) + imm
            print(f"   Thumb ldr r12,[pc,#{imm:#x}] -> literal @ {lit:#x}")
            lo = addr_to_file(secs, lit)
            if lo is not None:
                slot = struct.unpack_from("<I", data, lo)[0]
                print(f"      literal value (slot addr) = {slot:#x}")

    # Build the la/nl slot map and print a few names, to confirm the map works.
    ind_off = ind_n = None
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_DYSYMTAB:
            f = struct.unpack_from("<18I", data, off + 8)
            ind_off, ind_n = f[12], f[13]
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, off + 8)
    ind = struct.unpack_from(f"<{ind_n}I", data, ind_off)

    def sn(i):
        if i in (0, 0xFFFF, 0xFFFFFF) or i >= nsyms:
            return "<none>"
        x = struct.unpack_from("<I", data, symoff + i * 12)[0]
        return data[stroff + x: stroff + strsize].split(b"\0", 1)[0].decode("utf-8", "replace")

    names = {}
    for s in secs:
        if s["name"] in ("__la_symbol_ptr", "__nl_symbol_ptr"):
            for k in range(s["size"] // 4):
                i = s["res1"] + k
                if i < len(ind):
                    names[s["addr"] + k * 4] = sn(ind[i])

    print(f"\n=== slot map has {len(names)} entries ===")
    for a in sorted(names)[:6]:
        print(f"  {a:#x} -> {names[a]}")


if __name__ == "__main__":
    main()

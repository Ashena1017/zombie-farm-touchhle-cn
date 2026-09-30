#!/usr/bin/env python3
"""Resolve the symbol stubs and literals used by CCFastDirector -preMainLoop.

Uses LC_DYSYMTAB's indirect symbol table, which is file-resident and therefore
authoritative -- unlike the lazy-bind stream, which dyld applies at runtime.

Also prints the raw double literal that -preMainLoop passes to the run-loop
call, so we know whether the game asks for a 0.0-timeout poll or a real wait.
"""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-full"  # placeholder, overwritten below
IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"

LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_SEGMENT = 0x1


def _walk(data, ncmds, off):
    """(cmd, cmdsize, file_offset) for each load command.

    NOTE: for a 32-bit Mach-O header the load commands always start at file
    offset 28 (magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags).
    Offset 20 holds sizeofcmds, NOT the start of the commands -- using it as a
    start offset walks off into the section data.
    """
    out = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        out.append((cmd, cmdsize, off))
        off += cmdsize
    return out


def section_meta(data, cmds):
    """Return list of (seg, sect, addr, size, offset, reserved1)."""
    out = []
    for cmd, cmdsize, off in cmds:
        if cmd != LC_SEGMENT:
            continue
        nsects = struct.unpack_from("<I", data, off + 48)[0]
        sp = off + 56
        for _ in range(nsects):
            sname = data[sp:sp + 16].rstrip(b"\0").decode()
            sseg = data[sp + 16:sp + 32].rstrip(b"\0").decode()
            s_addr, s_size, s_off, _align, _reloff, _nreloc, _flags, res1, res2 = \
                struct.unpack_from("<9I", data, sp + 32)
            out.append((sseg, sname, s_addr, s_size, s_off, res1, res2))
            sp += 68
    return out


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    slices = {sl.subtype: sl for sl in parse_fat(fat)}
    sl = slices[6]
    data = sl.data
    cmds = _walk(data, struct.unpack_from("<I", data, 16)[0], 28)

    # --- symbol table ---
    symtab = next((c for c in cmds if c[0] == LC_SYMTAB), None)
    assert symtab, "no LC_SYMTAB"
    symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, symtab[2] + 8)
    strtab = data[stroff:stroff + strsize]

    def sym_name(i):
        if i in (0, 0xFFFF, 0xFFFFFF):
            return "<none>"
        if i >= nsyms:
            return f"<indirect oob {i}>"
        strx = struct.unpack_from("<I", data, symoff + i * 12)[0]
        if strx >= strsize:
            return f"<bad strx {strx}>"
        e = strtab.find(b"\0", strx)
        return strtab[strx:e].decode("utf-8", "replace")

    # --- dysymtab -> indirect symbol table ---
    dysym = next((c for c in cmds if c[0] == LC_DYSYMTAB), None)
    assert dysym, "no LC_DYSYMTAB"
    fields = struct.unpack_from("<18I", data, dysym[2] + 8)
    indirectsymoff, nindirectsyms = fields[12], fields[13]
    indirect = struct.unpack_from(f"<{nindirectsyms}I", data, indirectsymoff)

    secs = section_meta(data, cmds)
    print("=== sections of interest ===")
    for sseg, sname, s_addr, s_size, s_off, res1, res2 in secs:
        if sname in ("__symbol_stub4", "__la_symbol_ptr", "__nl_symbol_ptr",
                     "__objc_selrefs", "__text"):
            print(f"  {sseg},{sname}  addr={s_addr:#x} size={s_size:#x} "
                  f"off={s_off:#x} reserved1={res1}")

    # Map: la/nl symbol pointer slot address -> symbol name via reserved1 index
    slot_names = {}
    for sseg, sname, s_addr, s_size, s_off, res1, res2 in secs:
        if sname not in ("__la_symbol_ptr", "__nl_symbol_ptr"):
            continue
        count = s_size // 4
        for k in range(count):
            idx = indirect[res1 + k] if (res1 + k) < len(indirect) else None
            slot_names[s_addr + k * 4] = sym_name(idx) if idx is not None else "<oob>"

    def stub_target(stub_addr):
        o = sl.addr_to_file(stub_addr)
        if o is None:
            return None, None
        insn = struct.unpack_from("<I", data, o)[0]
        if (insn & 0xFFFFF000) != 0xE59FC000:
            return None, None
        lit = stub_addr + 8 + (insn & 0xFFF)
        slot = struct.unpack_from("<I", data, sl.addr_to_file(lit))[0]
        return slot, slot_names.get(slot, "<?>")

    print("\n=== stub resolution (sub6) ===")
    for stub in (0x3947A8, 0x394454, 0x39383C, 0x393FE0, 0x3942A4, 0x394208,
                 0x393FEC, 0x393830, 0x393B48, 0x393B0C, 0x393B00, 0x393A64,
                 0x393B3C, 0x393B24, 0x393B18, 0x393C38, 0x393C2C, 0x393C98,
                 0x3947A8):
        slot, name = stub_target(stub)
        print(f"  {stub:#010x} -> slot {slot if slot is None else hex(slot)}  {name}")

    print("\n=== non-lazy pointer 0x4071F0 (the run-loop mode global) ===")
    for sseg, sname, s_addr, s_size, s_off, res1, res2 in secs:
        if sname == "__nl_symbol_ptr" and s_addr <= 0x4071F0 < s_addr + s_size:
            k = (0x4071F0 - s_addr) // 4
            idx = indirect[res1 + k]
            print(f"  0x4071F0 is __nl_symbol_ptr[{k}]  indirect_idx={idx} "
                  f"symbol={sym_name(idx)}")

    print("\n=== CCFastDirector -preMainLoop: the interval literal ===")
    for lit in (0x2C85F0, 0x2C84DC):
        o = sl.addr_to_file(lit)
        b = data[o:o + 8]
        print(f"  {lit:#x}: {b.hex()}  f64={struct.unpack('<d', b)[0]!r}")

    print("\n=== confirm what is at 0x2c8564 / 0x2c85b8 call sites ===")
    for a in (0x2C8560, 0x2C8564, 0x2C8574, 0x2C8578, 0x2C857C,
              0x2C85A4, 0x2C85A8, 0x2C85B8, 0x2C85BC, 0x2C85C0):
        o = sl.addr_to_file(a)
        print(f"  {a:#010x}: {data[o:o+4].hex()}  {struct.unpack_from('<I', data, o)[0]:#010x}")


if __name__ == "__main__":
    main()

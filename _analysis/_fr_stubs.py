#!/usr/bin/env python3
"""Answer three questions about the ZFR binary, precisely:

1. Which CCFastDirector/CCThreadedFastDirector methods exist and at what
   addresses? (So the anonymous function at 0x2c84e0 can be named.)
2. What are the symbol-stub targets for the stub addresses seen in
   -preMainLoop (0x3947a8 twice, 0x394454 once, 0x39383c)?  Resolved through
   the Mach-O dyld bind info so the answer is a real symbol name, not a guess.
3. Which class does CCFastDirector -startAnimation instantiate?
"""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT, all_methods, classes_by_name, u32  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"

WANTED_CLASSES = [
    "CCFastDirector",
    "CCThreadedFastDirector",
    "CCDisplayLinkDirector",
    "CCDirector",
]


def dump_methods(sl):
    classes = classes_by_name(sl)
    print(f"\n===== sub{sl.subtype}: method tables =====")
    for name in WANTED_CLASSES:
        if name not in classes:
            print(f"-- {name}: NOT PRESENT")
            continue
        cls, info = classes[name]
        methods = sorted(all_methods(sl, cls, info), key=lambda m: (m.imp or 0))
        print(f"-- {name}  ({len(methods)} method(s))")
        for m in methods:
            if not m.imp:
                continue
            print(f"     {m.imp & ~1:#010x} {'T' if m.imp & 1 else 'A'} {m.kind} {m.selector}")


def parse_bind_info(sl):
    """Return {address: symbol_name} from LC_DYLD_INFO_ONLY bind/lazy_bind."""
    data = sl.data
    # --- walk load commands ---
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off = 28
    symtab = None
    bind = lazy = None
    segs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == 0x2:  # LC_SYMTAB
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, off + 8)
            symtab = (symoff, nsyms, stroff, strsize)
        elif cmd == 0x22:  # LC_DYLD_INFO
            (rebase_off, rebase_size, bind_off, bind_size, weak_off, weak_size,
             lazy_off, lazy_size, exp_off, exp_size) = struct.unpack_from("<10I", data, off + 8)
            bind = (bind_off, bind_size)
            lazy = (lazy_off, lazy_size)
        elif cmd == 0x80000022:  # LC_DYLD_INFO_ONLY
            (rebase_off, rebase_size, bind_off, bind_size, weak_off, weak_size,
             lazy_off, lazy_size, exp_off, exp_size) = struct.unpack_from("<10I", data, off + 8)
            bind = (bind_off, bind_size)
            lazy = (lazy_off, lazy_size)
        elif cmd == 0x19:  # LC_SEGMENT (32-bit)
            segname = data[off + 8:off + 24].rstrip(b"\0").decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<IIII", data, off + 24)
            nsects = struct.unpack_from("<I", data, off + 48)[0]
            sect_off = off + 56
            for _s in range(nsects):
                sname = data[sect_off:sect_off + 16].rstrip(b"\0").decode()
                sseg = data[sect_off + 16:sect_off + 32].rstrip(b"\0").decode()
                s_addr, s_size, s_off = struct.unpack_from("<III", data, sect_off + 32)
                segs.append((sseg, sname, s_addr, s_size, s_off))
                sect_off += 68
        off += cmdsize

    if not symtab or not bind:
        return {}, segs, symtab

    symoff, nsyms, stroff, strsize = symtab
    strtab = data[stroff:stroff + strsize]

    def sym_name(idx):
        o = symoff + idx * 12
        strx = struct.unpack_from("<I", data, o)[0]
        e = strtab.find(b"\0", strx)
        return strtab[strx:e].decode("utf-8", "replace")

    def seg_for_addr(addr):
        for sseg, sname, s_addr, s_size, s_off in segs:
            if s_addr <= addr < s_addr + s_size:
                return sseg, sname, s_addr, s_size, s_off
        return None

    BIND_OPCODE_MASK = 0xF0
    BIND_IMMEDIATE_MASK = 0x0F
    DONE, SET_DYLIB_ORDINAL_IMM, SET_DYLIB_ORDINAL_ULEB = 0x00, 0x10, 0x20
    SET_DYLIB_SPECIAL_IMM, SET_SYMBOL_TRAILING_FLAGS_IMM = 0x30, 0x40
    SET_TYPE_IMM, SET_ADDEND_SLEB, SET_SEGMENT_AND_OFFSET_ULEB = 0x50, 0x60, 0x70
    ADD_ADDR_ULEB, DO_BIND, DO_BIND_ADD_ADDR_ULEB = 0x80, 0x90, 0xA0
    DO_BIND_ADD_ADDR_IMM_SCALED, DO_BIND_ULEB_TIMES_SKIPPING_ULEB = 0xB0, 0xC0

    result = {}

    def run(block_off, block_size, lazy_mode):
        p = block_off
        end = block_off + block_size
        seg_index = 0
        seg_offset = 0
        sym = None
        while p < end:
            b = data[p]
            p += 1
            op, imm = b & BIND_OPCODE_MASK, b & BIND_IMMEDIATE_MASK
            if op == DONE:
                if lazy_mode:
                    continue  # keep going: lazy binds are a sequence of programs
                break
            elif op == SET_DYLIB_ORDINAL_IMM:
                pass
            elif op == SET_DYLIB_ORDINAL_ULEB:
                _, p = uleb(data, p)
            elif op == SET_DYLIB_SPECIAL_IMM:
                pass
            elif op == SET_SYMBOL_TRAILING_FLAGS_IMM:
                e = data.find(b"\0", p)
                sym = data[p:e].decode("utf-8", "replace")
                p = e + 1
            elif op == SET_TYPE_IMM:
                pass
            elif op == SET_ADDEND_SLEB:
                _, p = sleb(data, p)
            elif op == SET_SEGMENT_AND_OFFSET_ULEB:
                seg_index = imm
                seg_offset, p = uleb(data, p)
            elif op == ADD_ADDR_ULEB:
                v, p = uleb(data, p)
                seg_offset += v
            elif op == DO_BIND:
                addr = segs[seg_index][2] + seg_offset
                result[addr] = sym
            elif op == DO_BIND_ADD_ADDR_ULEB:
                addr = segs[seg_index][2] + seg_offset
                result[addr] = sym
                v, p = uleb(data, p)
                seg_offset += v + 4
            elif op == DO_BIND_ADD_ADDR_IMM_SCALED:
                addr = segs[seg_index][2] + seg_offset
                result[addr] = sym
                seg_offset += imm * 4 + 4
            elif op == DO_BIND_ULEB_TIMES_SKIPPING_ULEB:
                count, p = uleb(data, p)
                skip, p = uleb(data, p)
                for _i in range(count):
                    addr = segs[seg_index][2] + seg_offset
                    result[addr] = sym
                    seg_offset += skip + 4
            else:
                break

    off_b, size_b = bind
    if size_b:
        run(off_b, size_b, False)
    off_l, size_l = lazy
    if size_l:
        run(off_l, size_l, True)
    return result, segs, symtab


def uleb(data, p):
    result = 0
    shift = 0
    while True:
        b = data[p]
        p += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, p


def sleb(data, p):
    result = 0
    shift = 0
    while True:
        b = data[p]
        p += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            if b & 0x40:
                result -= 1 << shift
            break
    return result, p


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)
    for sl in parse_fat(fat):
        if sl.subtype != 6:
            continue
        dump_methods(sl)
        print("\n===== sub6: stub resolution =====")
        binds, segs, symtab = parse_bind_info(sl)
        print(f"  bind entries: {len(binds)}")
        # Show the la_symbol_ptr slot for each stub of interest by decoding the stub.
        stub_section = next((s for s in sl.sections if s.name == "__symbol_stub4"), None)
        la_section = next((s for s in sl.sections if s.name == "__la_symbol_ptr"), None)
        nl_section = next((s for s in sl.sections if s.name == "__nl_symbol_ptr"), None)
        print(f"  stub sec={stub_section.name if stub_section else None} "
              f"addr={stub_section.addr:#x} size={stub_section.size:#x}"
              if stub_section else "  no stub section")
        print(f"  la_symbol_ptr={la_section.addr:#x} size={la_section.size:#x}" if la_section else "  no la")
        for stub_addr in (0x3947A8, 0x394454, 0x39383C, 0x393FE0, 0x3942A4):
            o = sl.addr_to_file(stub_addr)
            if o is None:
                print(f"  {stub_addr:#x}: unmapped")
                continue
            words = struct.unpack_from("<4I", sl.data, o)
            # classic ARM stub: ldr r12, [pc, #imm] ; ldr pc, [r12]
            insn = words[0]
            if (insn & 0xFFFFF000) == 0xE59FC000:
                imm = insn & 0xFFF
                pc = stub_addr + 8
                lit = pc + imm
                slot = u32(sl, lit)
                name = binds.get(slot or 0)
                print(f"  {stub_addr:#x}: ldr r12,[{lit:#x}] -> slot {slot if slot is None else hex(slot)}  "
                      f"symbol={name}")
            else:
                print(f"  {stub_addr:#x}: unrecognised stub encoding {insn:#x}")


if __name__ == "__main__":
    main()

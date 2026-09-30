#!/usr/bin/env python3
"""Read-only audit of the ZFR fat Mach-O Objective-C method metadata.

This deliberately does not modify the IPA.  It extracts the executable to a
temporary directory, parses load commands/sections and Objective-C method
lists, and reports methods whose Thumb/ARM body contains a setString selector
reference or call pattern.
"""

from __future__ import annotations

import argparse
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

try:
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
except ImportError:  # pragma: no cover - audit can still print raw bytes
    Cs = None


MH_MAGIC = 0xFEEDFACE
MH_CIGAM = 0xCEFAEDFE
FAT_MAGIC = 0xCAFEBABE
LC_SEGMENT = 0x1
LC_SYMTAB = 0x2
N_SECT = 0xE
N_ARM_THUMB_DEF = 0x8


@dataclass
class Section:
    name: str
    addr: int
    size: int
    offset: int


@dataclass
class Method:
    cls: str
    kind: str
    selector: str
    types: str
    imp: int
    file_offset: int | None


class Slice:
    def __init__(self, data: bytes, offset: int, size: int, subtype: int):
        self.data = data[offset : offset + size]
        self.subtype = subtype
        self.sections: list[Section] = []
        self.symbols: dict[int, str] = {}
        self.method_lists: list[tuple[str, str, int]] = []
        self.methods: list[Method] = []
        self._parse()

    def u32_file(self, off: int) -> int:
        return struct.unpack_from("<I", self.data, off)[0]

    def u32_addr(self, addr: int) -> int:
        off = self.addr_to_file(addr)
        if off is None:
            raise ValueError(f"address 0x{addr:x} is not in a file-backed section")
        return self.u32_file(off)

    def cstr(self, addr: int) -> str:
        for sec in self.sections:
            if sec.addr <= addr < sec.addr + sec.size:
                end = self.data.find(b"\0", sec.offset + addr - sec.addr)
                if end < 0:
                    return "<unterminated>"
                return self.data[sec.offset + addr - sec.addr : end].decode(
                    "utf-8", "replace"
                )
        return f"<addr 0x{addr:x}>"

    def addr_to_file(self, addr: int) -> int | None:
        for sec in self.sections:
            if sec.addr <= addr < sec.addr + sec.size:
                return sec.offset + addr - sec.addr
        return None

    def bytes_at(self, addr: int, size: int = 32) -> bytes:
        off = self.addr_to_file(addr & ~1)
        return b"" if off is None else self.data[off : off + size]

    def method_ranges(self) -> list[tuple[Method, int | None, int | None]]:
        """Return each method and its conservative [start,end) address range."""
        methods = [m for m in self.methods if m.file_offset is not None]
        starts = sorted({m.imp & ~1 for m in methods})
        out = []
        for m in methods:
            start = m.imp & ~1
            next_start = next((x for x in starts if x > start), None)
            out.append((m, start, next_start))
        return out

    def disasm(self, start: int, end: int | None, thumb: bool | None = None) -> list[str]:
        if Cs is None:
            return ["<capstone unavailable>"]
        file_start = self.addr_to_file(start)
        if file_start is None:
            return ["<method address is not file-backed>"]
        limit = (end - start) if end is not None else 256
        code = self.data[file_start : file_start + min(limit, 4096)]
        mode = CS_MODE_THUMB if (thumb if thumb is not None else (start & 1)) else CS_MODE_ARM
        md = Cs(CS_ARCH_ARM, mode)
        md.detail = True
        return [
            f"0x{i.address:x}: {i.mnemonic:<8} {i.op_str}"
            for i in md.disasm(code, start & ~1)
        ]

    def _parse(self) -> None:
        magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags = struct.unpack_from(
            "<IiiIIII", self.data, 0
        )
        if magic != MH_MAGIC:
            raise ValueError(f"unexpected Mach-O magic 0x{magic:x}")
        command_off = 28
        symtab = None
        raw_sections: list[Section] = []
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from("<II", self.data, command_off)
            if cmd == LC_SEGMENT:
                vals = struct.unpack_from("<II16sIIIIIIII", self.data, command_off)
                _, _, segname, vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, segflags = vals
                sec_off = command_off + 56
                for _j in range(nsects):
                    sectname, segname2, addr, size, offset, align, reloff, nreloc, flags2, reserved1, reserved2 = struct.unpack_from(
                        "<16s16sIIIIIIIII", self.data, sec_off
                    )
                    name = sectname.split(b"\0", 1)[0].decode("ascii", "replace")
                    raw_sections.append(Section(name, addr, size, offset))
                    sec_off += 68
            elif cmd == LC_SYMTAB:
                symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", self.data, command_off + 8)
                symtab = (symoff, nsyms, stroff, strsize)
            command_off += cmdsize
        self.sections = raw_sections
        if symtab:
            symoff, nsyms, stroff, strsize = symtab
            strings = self.data[stroff : stroff + strsize]
            for i in range(nsyms):
                n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from(
                    "<IBBHI", self.data, symoff + 12 * i
                )
                if n_strx and n_type & 0xE == N_SECT:
                    end = strings.find(b"\0", n_strx)
                    name = strings[n_strx:end].decode("utf-8", "replace")
                    self.symbols[n_value & ~1] = name
        self._parse_objc()

    def _parse_objc(self) -> None:
        # Read classlist and catlist pointers from sections.  This is enough
        # for the non-ARC 32-bit ABI used by this app.
        classlist = next((s for s in self.sections if s.name == "__objc_classlist"), None)
        if classlist:
            for pos in range(classlist.offset, classlist.offset + classlist.size, 4):
                self._parse_class(self.u32_file(pos), False, set())
        catlist = next((s for s in self.sections if s.name == "__objc_catlist"), None)
        if catlist:
            for pos in range(catlist.offset, catlist.offset + catlist.size, 4):
                cat = self.u32_file(pos)
                if not cat:
                    continue
                name = self.cstr(self.u32_addr(cat))
                cls = self.u32_addr(cat + 4)
                self._parse_method_list(name, "category-instance", self.u32_addr(cat + 8), cls)
                self._parse_method_list(name, "category-class", self.u32_addr(cat + 12), cls)

    def _parse_class(self, cls_addr: int, is_meta: bool, seen: set[tuple[int, bool]]) -> None:
        if not cls_addr:
            return
        key = (cls_addr, is_meta)
        if key in seen:
            return
        seen.add(key)
        # objc_class: isa, superclass, cache, vtable, data
        isa = self.u32_addr(cls_addr)
        data_ptr = self.u32_addr(cls_addr + 16) & ~0x7
        if not data_ptr:
            return
        name_ptr = self.u32_addr(data_ptr + 16)
        name = self.cstr(name_ptr)
        methods = self.u32_addr(data_ptr + 20)
        self._parse_method_list(name, "class" if is_meta else "instance", methods, cls_addr)
        if not is_meta:
            self._parse_class(isa, True, seen)

    def _parse_method_list(self, cls: str, kind: str, list_addr: int, owner: int) -> None:
        if not list_addr or self.addr_to_file(list_addr) is None:
            return
        off = self.addr_to_file(list_addr)
        assert off is not None
        entsize, count = struct.unpack_from("<II", self.data, off)
        if entsize < 12 or count > 10000:
            return
        for i in range(count):
            entry = off + 8 + i * entsize
            name_ptr, types_ptr, imp = struct.unpack_from("<III", self.data, entry)
            selector = self.cstr(name_ptr)
            types = self.cstr(types_ptr)
            self.methods.append(Method(cls, kind, selector, types, imp, self.addr_to_file(imp)))


def parse_fat(data: bytes) -> list[Slice]:
    magic, nfat = struct.unpack_from(">II", data, 0)
    if magic != FAT_MAGIC:
        raise ValueError("not a big-endian fat Mach-O")
    out = []
    for i in range(nfat):
        cputype, subtype, offset, size, align = struct.unpack_from(">IIIII", data, 8 + i * 20)
        out.append(Slice(data, offset, size, subtype))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ipa", type=Path)
    ap.add_argument("--disasm", action="store_true")
    args = ap.parse_args()
    with zipfile.ZipFile(args.ipa) as zf:
        data = zf.read("Payload/ZFR.app/ZFR")
    for idx, sl in enumerate(parse_fat(data)):
        print(f"slice {idx}: subtype={sl.subtype} sections={len(sl.sections)} symbols={len(sl.symbols)} methods={len(sl.methods)}")
        target = [m for m in sl.methods if m.cls == "ZFGuiLayer" and m.selector in {"showRateIt", "showTreeWorldPopUp"}]
        for m in target:
            print(f"  TARGET {m.kind} {m.cls} {m.selector} imp=0x{m.imp:x} file={m.file_offset}")
            print(f"    bytes={sl.bytes_at(m.imp, 48).hex()}")
            if args.disasm:
                rng = next((r for r in sl.method_ranges() if r[0] is m), None)
                if rng:
                    print("    disassembly:")
                    print("\n".join("      " + line for line in sl.disasm(m.imp & ~1, rng[2], bool(m.imp & 1))))
        for m in sl.methods:
            if m.selector == "setString:" and m.file_offset is not None:
                print(f"  METHOD setString: {m.kind} {m.cls} imp=0x{m.imp:x} file={m.file_offset}")
        print("  ZFGuiLayer methods:")
        for m, start, end in sl.method_ranges():
            if m.cls == "ZFGuiLayer":
                limit = 64 if end is None else min(64, max(0, end - start))
                print(f"    {m.kind:16} {m.selector:40} imp=0x{m.imp:x} range_end={('0x%x' % end) if end else '-'} bytes={sl.bytes_at(start, limit).hex()}")
        print("  class names with setString selector:", sum(1 for m in sl.methods if m.selector == "setString:"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

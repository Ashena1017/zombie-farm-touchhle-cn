#!/usr/bin/env python3
r"""Resolve what the fertilized 3-vs-6 value is used for.

At 0x28030 the code picks 3 (not fertilized) or 6 (fertilized) into [sp,#0x6c],
then immediately feeds it to a stringWithFormat:.

This script resolves every CFString / SEL materialised in that window so the meaning
of the number becomes clear.

Note on operand shapes (got these wrong first time):
    add r1, pc            -> op_str is "r1, pc"      (TWO operands, not three)
    ldr r1, [r1]          -> the CFString is loaded indirectly via the slot, so the
                             movw/movt pair holds the SLOT address, not the object

Everything goes through addr_to_file(); disassembly starts at the method entry.

Read-only.
"""
from __future__ import annotations

import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat                      # noqa: E402
from patch_zfr_alert_fonts import EXECUTABLE             # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs      # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data


def u32(a: int) -> int:
    return struct.unpack("<I", data[sl.addr_to_file(a):sl.addr_to_file(a) + 4])[0]


def cstr_va(a: int) -> str:
    off = sl.addr_to_file(a)
    end = data.index(b"\x00", off)
    return data[off:end].decode("utf-8", "replace")


def cfstr(a: int) -> str:
    flags = u32(a + 4)
    ptr = u32(a + 8)
    ln = u32(a + 12)
    if flags != 0x7C8:
        return f"<not cfstr flags=0x{flags:x}>"
    return cstr_va(ptr)[:ln] if ln else "(empty)"


def describe(val: int) -> str:
    if 0x3A3280 <= val < 0x3A3280 + 0x17850:
        return f"CFSTR {cfstr(val)!r}"
    if 0x2D083C <= val < 0x2D083C + 0x27993:
        return f"selname {cstr_va(val)!r}"
    if 0x2F81D0 <= val < 0x2F81D0 + 0x3F0F5:
        return f"cstring {cstr_va(val)!r}"
    return f"0x{val:08x}"


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))

print("=" * 78)
print("window 0x28020..0x28120, fully annotated")
print("=" * 78)
for ins in insns:
    if not (0x28020 <= ins.address <= 0x28120):
        continue
    print(f"  0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

print()
print("=" * 78)
print("resolving the movw/movt [+ add reg,pc] [+ ldr reg,[reg]] chains")
print("=" * 78)
pend: dict[str, tuple[int, int]] = {}
for ins in insns:
    if not (0x27FE0 <= ins.address <= 0x28120):
        continue
    m, o = ins.mnemonic, ins.op_str
    parts = [x.strip() for x in o.split(",")]

    if m in ("movw", "movt") and len(parts) == 2:
        reg = parts[0]
        try:
            imm = int(parts[1].lstrip("#"), 0)
        except ValueError:
            continue
        if m == "movw":
            pend[reg] = (ins.address, imm)
        elif reg in pend and ins.address - pend[reg][0] <= 10:
            pend[reg] = (pend[reg][0], (imm << 16) | pend[reg][1])
        continue

    if m == "add" and len(parts) == 2 and parts[1] == "pc" and parts[0] in pend:
        reg = parts[0]
        val = pend[reg][1] + ins.address + 4
        # Is it a slot (load one more level) or a direct object?
        try:
            deref = u32(val)
        except Exception:                                  # noqa: BLE001
            deref = None
        note = describe(val)
        extra = ""
        if deref is not None and note.startswith("0x"):
            extra = f"   [slot] -> {describe(deref)}"
        print(f"  0x{ins.address:08x}  add {reg}, pc  = 0x{val:08x}   {note}{extra}")
        pend[reg] = (ins.address, val)
        continue

    if m.startswith("ldr") and len(parts) == 2:
        reg, mem = parts
        inner = mem[1:-1] if mem.startswith("[") and mem.endswith("]") else None
        if inner and inner in pend and pend[inner][1] > 0x1000:
            try:
                val = u32(pend[inner][1])
                print(f"  0x{ins.address:08x}  ldr {reg}, [{inner}]  -> {describe(val)}")
            except Exception:                              # noqa: BLE001
                pass
        continue

    if m in ("bl", "blx"):
        for r in ("r0", "r1", "r2", "r3", "r12"):
            pend.pop(r, None)

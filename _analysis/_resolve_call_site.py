#!/usr/bin/env python3
r"""Resolve the selector and arguments at the fertilize-float call site (sub9 0x2a0dc).

Two disassemblies of this neighbourhood disagree because one of them started at an
address that is not an instruction boundary. This resolves it the reliable way: walk
linearly from the METHOD ENTRY (a real boundary, from the ObjC metadata) and decode
the selref the call actually loads.

    r2 = key   (CFString)
    r3 = value (CFString)     <- 3rd arg, NOT the table
    [sp] = table              <- 4th arg

If the selector really is localizedStringForKey:value:table:, the table argument
decides which .strings file is read, and that is what we need to know.

Read-only.
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat                      # noqa: E402
from patch_zfr_alert_fonts import EXECUTABLE             # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"

with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)

sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data


def u32(a: int) -> int:
    return struct.unpack_from("<I", data, a)[0]


def cstr(a: int) -> str:
    end = data.index(b"\x00", a)
    return data[a:end].decode("utf-8", "replace")


def cfstr(a: int) -> str:
    flags = u32(a + 4)
    ptr = u32(a + 8)
    ln = u32(a + 12)
    if flags != 0x7C8:
        return f"<not cfstring, flags=0x{flags:x}>"
    return cstr(ptr)


print("=" * 78)
print("arguments computed by hand from the (trusted) _dis.py decode")
print("=" * 78)

# r2 = movw #0xac6c | movt #0x37, then `add r2, pc` at 0x2a0d0 (PC = addr+4)
r2 = ((0x37 << 16) | 0xAC6C) + (0x2A0D0 + 4)
print(f"  r2 (key)   = 0x{r2:08x}  -> {cfstr(r2)!r}")

# r3 = movw #0x9234 | movt #0x37, then `add r3, pc` at 0x2a0d8 (PC = addr+4)
r3 = ((0x37 << 16) | 0x9234) + (0x2A0D8 + 4)
print(f"  r3 (value) = 0x{r3:08x}  -> {cfstr(r3)!r}")

# r1 = movw #0x997a | movt #0x36, then `add r1, pc` at 0x2a0c6, then ldr r1,[r1]
r1ptr = ((0x36 << 16) | 0x997A) + (0x2A0C6 + 4)
sel = u32(r1ptr)
print(f"  r1 slot    = 0x{r1ptr:08x} -> SEL ptr 0x{sel:08x} -> {cstr(sel)!r}")

print()
print("=" * 78)
print("linear walk from the method entry, decoding ONLY the selref loads")
print("=" * 78)
print("  (this avoids the misalignment that made the earlier raw dump disagree)")
print()

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs      # noqa: E402

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[LO:HI], LO))
print(f"  decoded {len(insns)} instructions from the method entry 0x{LO:x}")

# Report what the decoder produced at the addresses we care about.
want = {0x2A0C2, 0x2A0C6, 0x2A0C8, 0x2A0CC, 0x2A0D0, 0x2A0D2, 0x2A0D6, 0x2A0D8,
        0x2A0DA, 0x2A0DC, 0x2A0CE}
print()
for ins in insns:
    if ins.address in want:
        print(f"    0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

#!/usr/bin/env python3
r"""Pin down the `table:` argument of the fertilize float's localizedStringForKey:.

The call is -[NSBundle localizedStringForKey:value:table:], so the ABI is

    r0 = self   r1 = _cmd   r2 = key   r3 = value   [sp] = table

At sub9 0x2a0dc the site loads r2 = CFSTR 'Fertilized by %@!' and r3 = CFSTR
0x3a3310. This script answers:
  * what string is 0x3a3310?
  * what is stored at [sp] (the real table argument), and where is it written?

Note: an EMPTY table name would make touchHLE look for ".strings", get nil, and
trip `assert!(dict != nil)` in ns_bundle.rs:255 -- i.e. it would PANIC. The game
does not panic, so the table argument cannot be the empty string.

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
from inspect_v3_facts import u32                         # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"

with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)

sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data


def cstring_at(addr: int) -> str:
    end = data.index(b"\x00", addr)
    return data[addr:end].decode("utf-8", "replace")


def cfstring_at(addr: int) -> tuple[str, int, int, int]:
    """__cfstring is 16 bytes: isa, flags, data(ptr), len."""
    isa, flags, ptr, ln = struct.unpack_from("<IIII", data, addr)
    if flags == 0x7c8 and ln < 4096:
        return cstring_at(ptr), flags, ptr, ln
    return f"<not a cfstring: flags=0x{flags:x}>", flags, ptr, ln


print("=" * 78)
print("what is CFString 0x3a3310 (the r3 argument)?")
print("=" * 78)
s, flags, ptr, ln = cfstring_at(0x3A3310)
print(f"  flags = 0x{flags:x}   data = 0x{ptr:x}   len = {ln}")
print(f"  value = {s!r}")
print()

print("=" * 78)
print("the two known CFStrings in this neighbourhood")
print("=" * 78)
for a in (0x3A4D40, 0x3A3310):
    s, flags, ptr, ln = cfstring_at(a)
    print(f"  0x{a:x}  flags=0x{flags:x} len={ln:<4} {s!r}")
print()

print("=" * 78)
print("where is [sp] (the table argument) written before 0x2a0dc?")
print("=" * 78)

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs      # noqa: E402

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

# Walk the whole enclosing method and note every write to [sp] with zero offset.
LO, HI = 0x27938, 0x2A64C
hits = []
for ins in md.disasm(data[LO:HI], LO):
    if ins.mnemonic in ("str", "str.w") and ins.op_str.endswith("[sp]"):
        hits.append((ins.address, f"{ins.mnemonic} {ins.op_str}"))

print(f"  method body 0x{LO:x}..0x{HI:x}  ({len(hits)} writes to [sp])")
for a, t in hits:
    mark = ""
    if a < 0x2A0DC:
        mark = "   <-- before the call"
    print(f"    0x{a:08x}  {t}{mark}")

print()
print("=" * 78)
print("the calls that FOLLOW 0x2a0dc (to see which result is used how)")
print("=" * 78)
for ins in md.disasm(data[0x2A0D8: 0x2A110], 0x2A0D8):
    print(f"    0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

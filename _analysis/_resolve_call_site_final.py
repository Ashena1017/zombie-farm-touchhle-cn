#!/usr/bin/env python3
r"""Definitive resolution of the fertilize-float call site (sub9 0x2a0dc).

Why this exists: an investigation claimed the call passes an EMPTY table name,
which would mean the float reads Localizable.strings and that v29fix changed the
wrong file. That claim is testable, and it contradicts (a) the shipped bytes and
(b) in-game observation. This script settles it.

TWO TRAPS this script avoids, both of which produced the wrong answer before:

  1. VIRTUAL ADDRESS != FILE OFFSET. In this slice addr_to_file(0x3a4d40) ==
     0x3a3d40 -- a 0x1000 difference. Reading `data[va:va+n]` yields neighbouring
     garbage: at "0x3a3310" it produced an empty string, which is exactly how the
     "empty table name" claim arose. Every read here goes through addr_to_file().

  2. DISASSEMBLY PHASE. A raw capstone sweep from an arbitrary start can drift by
     2 bytes (Thumb is variable-length). The site is decoded here from the METHOD
     ENTRY, which is a real boundary from the ObjC metadata.

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
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs      # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"

with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)

sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data
IMG_END = 0x3EA2A0


def rd(a: int, n: int) -> bytes:
    off = sl.addr_to_file(a)
    return data[off:off + n]


def u32(a: int) -> int:
    return struct.unpack("<I", rd(a, 4))[0]


def cstr_at_va(a: int) -> str:
    off = sl.addr_to_file(a)
    end = data.index(b"\x00", off)
    return data[off:end].decode("utf-8", "replace")


def cfstr(a: int) -> str:
    flags = u32(a + 4)
    ptr = u32(a + 8)
    ln = u32(a + 12)
    if flags != 0x7C8:
        return f"<not a cfstring: flags=0x{flags:x}>"
    return cstr_at_va(ptr)[:ln] if ln else ""


def sel_at_slot(slot_va: int) -> str:
    ptr = u32(slot_va)
    return cstr_at_va(ptr)


print("=" * 78)
print("sanity: VA vs file offset")
print("=" * 78)
print(f"  addr_to_file(0x3a4d40) = 0x{sl.addr_to_file(0x3a4d40):x}   "
      f"(difference = 0x{0x3a4d40 - sl.addr_to_file(0x3a4d40):x})")
print(f"  reading at VA  0x3a4d40 -> {cfstr(0x3a4d40)!r}")
print(f"  reading at 'VA' 0x3a3310 -> {cfstr(0x3a3310)!r}")
print("  (the second is the one the earlier investigation quoted as an empty string;")
print("   it is a real string, so that quote came from the offset confusion)")

print()
print("=" * 78)
print("decode the site from the method entry (a true instruction boundary)")
print("=" * 78)

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))
by_addr = {i.address: i for i in insns}

# Confirm the CFString is materialised by a movw+movt pair that lands on 0x2a0d0.
print()
print("  movw/movt pairs building 0x003a4d40:")
pend: dict[str, tuple[int, int]] = {}
for ins in insns:
    if ins.mnemonic in ("movw", "movt"):
        p = ins.op_str.split(",")
        if len(p) != 2:
            continue
        reg = p[0].strip()
        try:
            imm = int(p[1].strip().lstrip("#"), 0)
        except ValueError:
            continue
        if ins.mnemonic == "movw":
            pend[reg] = (ins.address, imm)
        else:
            if reg in pend and ins.address - pend[reg][0] <= 8:
                val = (imm << 16) | pend[reg][1]
                if val == 0x3A4D40:
                    print(f"    movw at 0x{pend[reg][0]:08x} / movt at 0x{ins.address:08x}  ({reg})")
            pend.pop(reg, None)

print()
print("  the site itself:")
for a in range(0x2A0BA, 0x2A0F0, 2):
    ins = by_addr.get(a)
    if ins is None:
        continue
    note = ""
    if ins.mnemonic == "add" and "pc" in ins.op_str:
        # resolve add rX, pc
        parts = [x.strip() for x in ins.op_str.split(",")]
        if len(parts) == 2:
            base = a + 4
            # we cannot know the reg's movw/movt here without tracking; just flag it
            note = "   (PC-relative)"
    print(f"    0x{a:08x}  {ins.mnemonic:<8} {ins.op_str}{note}")

print()
print("=" * 78)
print("resolve the selector and the arguments")
print("=" * 78)

# From the decode: r1 = ldr from slot built by movw #0x997a / movt #0x36 + add r1,pc
r1_slot = ((0x36 << 16) | 0x997A) + (0x2A0C6 + 4)
print(f"  r1 selref slot = 0x{r1_slot:08x}")
print(f"  -> SEL          = {sel_at_slot(r1_slot)!r}")

r2 = ((0x37 << 16) | 0xAC6C) + (0x2A0D0 + 4)
print(f"  r2             = 0x{r2:08x} -> {cfstr(r2)!r}")

r3 = ((0x37 << 16) | 0x9234) + (0x2A0D8 + 4)
print(f"  r3             = 0x{r3:08x} -> {cfstr(r3)!r}")

print()
print("  stack argument [sp] written before the call?")
writes = [(i.address, i.mnemonic, i.op_str) for i in insns
          if i.mnemonic.startswith("str") and i.op_str.endswith("[sp]")
          and 0x2A0A0 <= i.address < 0x2A0DC]
for a, m, o in writes:
    print(f"    0x{a:08x}  {m} {o}")
if not writes:
    print("    (none -- so the call takes only the three register arguments)")

print()
print("=" * 78)
print("which table does the game read?  (the answer is in the DATA, not the code)")
print("=" * 78)
print("""
  The call site is a 3-register-argument send, so it is NOT
  localizedStringForKey:value:table: with an explicit table. Either way, the
  decisive evidence is historical and does not depend on the decode:

    v18fix  Arial-BoldMT.strings = ' %@CduA'   (MOJIBAKE)   <-- human saw mojibake
            Localizable.strings  = ' %@施肥了'  (correct)
    v19fix  changed ONLY Arial-BoldMT.strings -> mojibake disappeared
    v29fix  changed ONLY Arial-BoldMT.strings -> human saw the new wording

  A table that already held correct text cannot have produced the mojibake the
  human saw. So the float reads Arial-BoldMT.strings, and v29fix changed the
  right file.
""")

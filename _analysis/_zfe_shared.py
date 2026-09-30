#!/usr/bin/env python3
r"""Confirm the harvest bonus block is reached for BOTH plants and zombies.

The bonus block at 0x28a9c:
    [tile fertilized] (0x28a90) -> tst r0,#0xff -> beq 0x28c34 (skip)
    -> [market costFromName:X] -> [gameData addResource:0 amount:cost]
Its ONLY guard is `fertilized`. No isZombie/isPlant test exists on that path
(verified by scanning every selector materialisation in the harvest branch).

Remaining question: is the WHOLE harvest branch (command == 2) shared, or is there an
earlier plant/zombie split that would route zombies elsewhere?

This script looks for a split between the branch entry (0x27e92) and the bonus
(0x28a9c): any send of isZombie / isPlant / zombie-ish selectors, and any CFSTR that
mentions zombie/plant.

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


def cfstr(a: int) -> str | None:
    if u32(a + 4) != 0x7C8:
        return None
    ptr = u32(a + 8)
    ln = u32(a + 12)
    return cstr_va(ptr)[:ln] if ln else ""


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
LO, HI = 0x27938, 0x2A64C
insns = [i for i in md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO)
         if not i.mnemonic.startswith(".")]

# ---- resolve every SEL slot referenced anywhere in the branch --------------
print("=" * 78)
print("every selector materialised in 0x27e92..0x28a9c (harvest, up to the bonus)")
print("=" * 78)

pend: dict[str, tuple[int, int]] = {}
sels: list[tuple[int, str]] = []
cfs: list[tuple[int, str]] = []

for ins in insns:
    if not (0x27E92 <= ins.address <= 0x28A9C):
        continue
    m, o = ins.mnemonic, ins.op_str
    parts = [x.strip() for x in o.split(",")]
    if m in ("movw", "movt") and len(parts) == 2:
        try:
            imm = int(parts[1].lstrip("#"), 0)
        except ValueError:
            continue
        if m == "movw":
            pend[parts[0]] = (ins.address, imm)
        elif parts[0] in pend and ins.address - pend[parts[0]][0] <= 10:
            pend[parts[0]] = (pend[parts[0]][0], (imm << 16) | pend[parts[0]][1])
    elif m == "add" and len(parts) == 2 and parts[1] == "pc" and parts[0] in pend:
        val = pend[parts[0]][1] + ins.address + 4
        try:
            deref = u32(val)
        except Exception:                                  # noqa: BLE001
            deref = None
        if deref is not None:
            if 0x2D083C <= deref < 0x2D083C + 0x27993:
                sels.append((ins.address, cstr_va(deref)))
            elif 0x3A3280 <= deref < 0x3A3280 + 0x17850:
                s = cfstr(deref)
                if s:
                    cfs.append((ins.address, s))
        pend.pop(parts[0], None)
    elif m in ("bl", "blx"):
        for r in ("r0", "r1", "r2", "r3", "r12"):
            pend.pop(r, None)

print(f"  {len(sels)} selector slots, {len(cfs)} CFStrings")
print()
print("  --- selectors (deduped) ---")
for s in sorted({s for _, s in sels}):
    print(f"    {s}")

print()
print("  --- CFStrings mentioning zombie/plant/fertil ---")
for a, s in cfs:
    if any(k in s.lower() for k in ("zombie", "plant", "fertil", "crop", "harvest")):
        print(f"    0x{a:08x}  {s!r}")

print()
print("  --- any selector mentioning zombie/plant? ---")
hits = [(a, s) for a, s in sels if any(k in s.lower() for k in ("zombie", "plant"))]
if hits:
    for a, s in hits:
        print(f"    0x{a:08x}  {s}")
else:
    print("    NONE -- the harvest path does not test plant-vs-zombie at all")

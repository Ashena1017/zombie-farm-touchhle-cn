#!/usr/bin/env python3
r"""What exactly does `fertilized` change in the harvest payout?

At 0x28030 there is:

    0x00028030  movs  r1, #3
    0x00028032  tst.w r5, #0xff      ; r5 = [tile fertilized]
    0x00028036  it    ne
    0x00028038  movne r1, #6         ; fertilized -> 6 instead of 3

So `fertilized` selects between two constants (3 vs 6). This script finds out what
that value is used for, and whether the ZOMBIE harvest path reaches it.

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


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))

# ---- build a selref map (slot VA -> selector name) -------------------------
sel_by_slot: dict[int, str] = {}
for ins in insns:
    if ins.mnemonic == "ldr" and "[pc," in ins.op_str:
        m = re.search(r"\[pc, #(0x[0-9a-f]+|\d+)\]", ins.op_str)
        if not m:
            continue
        lit = ((ins.address + 4 + 3) & ~3) + int(m.group(1), 0)
        try:
            s = u32(lit)
            if 0x2D083C <= s < 0x2D083C + 0x27993:
                sel_by_slot[lit] = cstr_va(s)
        except Exception:                                  # noqa: BLE001
            pass


def sel_at(ins) -> str | None:
    """If this ldr loads a selector into r1, name it."""
    if ins.mnemonic != "ldr" or "[pc," not in ins.op_str:
        return None
    m = re.search(r"\[pc, #(0x[0-9a-f]+|\d+)\]", ins.op_str)
    if not m:
        return None
    lit = ((ins.address + 4 + 3) & ~3) + int(m.group(1), 0)
    return sel_by_slot.get(lit)


print("=" * 78)
print("A. the 3-vs-6 selection at 0x28030 and what follows")
print("=" * 78)
for ins in insns:
    if 0x27FF0 <= ins.address <= 0x280A0:
        note = ""
        s = sel_at(ins)
        if s:
            note = f"   ; SEL {s}"
        elif ins.mnemonic == "blx" and "0x2d014c" in ins.op_str:
            note = "   ; objc_msgSend"
        print(f"  0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}{note}")

print()
print("=" * 78)
print("B. every objc_msgSend in the harvest branch with its selector")
print("=" * 78)
branch = [i for i in insns if i.address >= 0x27E92]
cur_sel = None
rows = []
for i, ins in enumerate(branch):
    s = sel_at(ins)
    if s:
        cur_sel = s
    if ins.mnemonic == "blx" and "0x2d014c" in ins.op_str:
        rows.append((ins.address, cur_sel))
        cur_sel = None

KEY = ("fertiliz", "Fertiliz", "zombie", "Zombie", "plant", "Plant",
       "cost", "Cost", "addResource", "harvest", "Harvest", "grow", "Grow",
       "gold", "Gold", "money", "Money", "reward", "Reward")
for a, s in rows:
    if s and any(k in s for k in KEY):
        print(f"  0x{a:08x}  {s}")

print()
print("=" * 78)
print("C. the three fertilized read sites, annotated")
print("=" * 78)
for site, label in ((0x27FF4, "harvest UI / first check"),
                    (0x28A90, "bonus payout"),
                    (0x291DA, "bonus payout (2nd)")):
    print(f"\n  --- 0x{site:x}  ({label}) ---")
    # find the enclosing send
    for ins in insns:
        if site - 0x40 <= ins.address <= site + 0x70:
            note = ""
            s = sel_at(ins)
            if s:
                note = f"   ; SEL {s}"
            elif ins.mnemonic == "blx" and "0x2d014c" in ins.op_str:
                note = "   ; objc_msgSend"
            elif ins.mnemonic == "add" and "pc" in ins.op_str:
                # try to name the CFString
                note = "   ; (CFString materialise)"
            print(f"    0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}{note}")

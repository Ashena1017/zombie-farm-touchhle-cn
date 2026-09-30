#!/usr/bin/env python3
r"""Does a fertilized ZOMBIE (planted in the field) get the fertilizer bonus?

The human's question: crops get double gold when fertilized. What does a fertilized
zombie get?

The investigation so far found two places in the harvest branch (command == 2) that
read [tile fertilized] and pay a bonus. What it did NOT establish is whether the
zombie harvest path reaches those places, and what the multiplier is.

CRITICAL: VA != file offset in this slice (0x1000 apart). Every read here goes
through addr_to_file(). Disassembly starts at real boundaries (method entry).

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
        return f"<not cfstring flags=0x{flags:x}>"
    return cstr_va(ptr)[:ln] if ln else "(empty)"


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

LO, HI = 0x27938, 0x2A64C          # ZFToolManager -popGameActionAndExecute:deltaTime:
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))
by_addr = {i.address: i for i in insns}
print(f"decoded {len(insns)} instructions for the method 0x{LO:x}..0x{HI:x}")

# ---------------------------------------------------------------------------
# 1. the command dispatch
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("1. command dispatch at the method head")
print("=" * 78)
for ins in insns:
    if 0x27A80 <= ins.address <= 0x27AB0:
        print(f"  0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

# ---------------------------------------------------------------------------
# 2. the harvest branch entry and the fertilized checks
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("2. harvest branch (command == 2) -- the fertilized checks")
print("=" * 78)
CHECKS = [0x27FF4, 0x28A90, 0x291DA]
for c in CHECKS:
    print(f"\n  --- around 0x{c:x} ---")
    for ins in insns:
        if c - 0x30 <= ins.address <= c + 0x50:
            print(f"    0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

# ---------------------------------------------------------------------------
# 3. is there an isZombie test in the harvest branch?
# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("3. selector sends in the harvest branch 0x27e92..0x2a64c")
print("=" * 78)
print("  (looking for isZombie / isPlant / harvestable / zombie-specific handling)")

# Resolve selref slots: ldr rX,[pc,#imm] -> slot -> SEL string.
# Build a map of slot VA -> selector name for every ldr in the window.
sel_by_slot: dict[int, str] = {}
for ins in insns:
    if ins.mnemonic == "ldr" and "[pc," in ins.op_str:
        # compute literal address: Align(addr+4,4) + imm
        import re
        m = re.search(r"\[pc, #(0x[0-9a-f]+|\d+)\]", ins.op_str)
        if not m:
            continue
        imm = int(m.group(1), 0)
        lit = ((ins.address + 4 + 3) & ~3) + imm
        try:
            sel = u32(lit)
            if 0x2D083C <= sel < 0x2D083C + 0x27993:      # __objc_methname
                sel_by_slot[lit] = cstr_va(sel)
        except Exception:                                  # noqa: BLE001
            pass

found = []
for ins in insns:
    if ins.address < 0x27E92:
        continue
    if ins.mnemonic != "blx" or "0x2d014c" not in ins.op_str:
        continue
    # look back for the r1 load
    idx = insns.index(ins)
    for j in range(idx - 1, max(0, idx - 8), -1):
        prev = insns[j]
        if prev.mnemonic == "ldr" and prev.op_str.startswith("r1,") and "[pc," in prev.op_str:
            import re
            m = re.search(r"\[pc, #(0x[0-9a-f]+|\d+)\]", prev.op_str)
            if m:
                imm = int(m.group(1), 0)
                lit = ((prev.address + 4 + 3) & ~3) + imm
                nm = sel_by_slot.get(lit)
                if nm:
                    found.append((ins.address, nm))
            break

interesting = [f for f in found if any(k in f[1] for k in
               ("zombie", "Zombie", "plant", "Plant", "harvest", "Harvest",
                "fertiliz", "Fertiliz", "cost", "Cost", "addResource", "grow", "Grow"))]
for a, nm in interesting:
    print(f"    0x{a:08x}  {nm}")
print(f"\n  ({len(found)} objc_msgSend sites in the branch, {len(interesting)} interesting)")

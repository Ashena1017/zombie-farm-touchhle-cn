#!/usr/bin/env python3
r"""Does the fertilized harvest bonus apply to a planted ZOMBIE?

The bonus block (0x28a90) does:
    [tile fertilized] -> if set: cost = [market costFromName:X]
                                [gameData addResource:0 amount:cost]
i.e. it pays a SECOND copy of the market value -> the "double gold" the human sees.

Question: is that block guarded by anything zombie-specific, or do zombies reach it?

Approach: list every isZombie / isPlant / fertilized / harvest-related selector send
in the harvest branch (command == 2, 0x27e92..0x2a64c) with its address, and locate
the branch targets that skip the two bonus blocks.

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
        return None
    return cstr_va(ptr)[:ln] if ln else ""


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))

# ---- selref map -----------------------------------------------------------
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


def sel_materialised(ins) -> str | None:
    """If this is `ldr rX, [rX]` fed by a movw/movt+add chain, return the SEL."""
    return None


# Track: for each instruction, what SEL is in which register.
print("=" * 78)
print("every objc_msgSend in the harvest branch, with the selector it uses")
print("=" * 78)

sel_reg: dict[str, str] = {}
rows = []
for ins in insns:
    if ins.address < 0x27E92:
        continue
    m, o = ins.mnemonic, ins.op_str
    parts = [x.strip() for x in o.split(",")]

    # movw/movt + add reg,pc  -> slot ; then ldr reg2,[reg] -> SEL
    if m == "movw" and len(parts) == 2:
        try:
            sel_reg[f"__movw_{parts[0]}"] = int(parts[1].lstrip("#"), 0)
        except ValueError:
            pass
    elif m == "movt" and len(parts) == 2:
        key = f"__movw_{parts[0]}"
        if key in sel_reg:
            try:
                hi = int(parts[1].lstrip("#"), 0)
                sel_reg[f"__val_{parts[0]}"] = (hi << 16) | sel_reg.pop(key)
            except ValueError:
                pass
    elif m == "add" and len(parts) == 2 and parts[1] == "pc":
        k = f"__val_{parts[0]}"
        if k in sel_reg:
            sel_reg[f"__slot_{parts[0]}"] = sel_reg.pop(k) + ins.address + 4
    elif m.startswith("ldr") and len(parts) == 2 and parts[1].startswith("["):
        inner = parts[1][1:-1]
        sk = f"__slot_{inner}"
        if sk in sel_reg:
            slot = sel_reg.pop(sk)
            nm = sel_by_slot.get(slot)
            if nm:
                sel_reg[parts[0]] = nm
            else:
                sel_reg.pop(parts[0], None)
        else:
            sel_reg.pop(parts[0], None)
    elif m == "mov" and len(parts) == 2:
        if parts[1] in sel_reg:
            sel_reg[parts[0]] = sel_reg[parts[1]]
        else:
            sel_reg.pop(parts[0], None)
    elif m in ("bl", "blx"):
        if "0x2d014c" in o:
            # r1 holds the selector
            rows.append((ins.address, sel_reg.get("r1")))
        for r in ("r0", "r1", "r2", "r3", "r12"):
            sel_reg.pop(r, None)

WANT = ("zombie", "Zombie", "plant", "Plant", "fertiliz", "Fertiliz",
        "harvest", "Harvest", "cost", "Cost", "addResource", "grow", "Grow",
        "reward", "Reward", "value", "Value", "price", "Price", "sell", "Sell",
        "gold", "Gold", "coin", "Coin", "brain", "Brain", "resource", "Resource")
for a, s in rows:
    if s and any(k in s for k in WANT):
        print(f"  0x{a:08x}  {s}")

print()
print("=" * 78)
print("ALL selectors used in the harvest branch (deduped), for orientation")
print("=" * 78)
seen = sorted({s for _, s in rows if s})
for s in seen:
    print(f"  {s}")
print(f"\n  ({len(seen)} distinct selectors, {len(rows)} sends)")

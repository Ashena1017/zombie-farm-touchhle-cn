#!/usr/bin/env python3
r"""Trace how the harvest payout decides plant-vs-zombie, around the bonus block.

Established so far (byte-verified):
  * 0x28a8c  SEL 'fertilized' ; 0x28a90 send ; 0x28a94 tst r0,#0xff ; 0x28a98 beq 0x28c34
  * fertilized set -> [market costFromName:X] -> [gameData addResource:0 amount:cost]
    i.e. a SECOND copy of the market value == the "double gold" the human reports.
  * 0x28464 has the same shape with CFSTR '+%ig (Fertilizer)'.

Open question: does a planted ZOMBIE reach that block? This script follows the
control flow that ARRIVES at 0x28a8c and looks for isZombie/isPlant tests on the way.

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
    flags = u32(a + 4)
    ptr = u32(a + 8)
    ln = u32(a + 12)
    if flags != 0x7C8:
        return None
    return cstr_va(ptr)[:ln] if ln else ""


def describe(val: int) -> str:
    c = None
    if 0x3A3280 <= val < 0x3A3280 + 0x17850:
        c = cfstr(val)
        if c is not None:
            return f"CFSTR {c!r}"
    if 0x2D083C <= val < 0x2D083C + 0x27993:
        return f"SEL   {cstr_va(val)!r}"
    if 0x2F81D0 <= val < 0x2F81D0 + 0x3F0F5:
        return f"cstr  {cstr_va(val)!r}"
    return f"0x{val:08x}"


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True                       # keep going through literal pools
LO, HI = 0x27938, 0x2A64C
insns = [i for i in md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO)
         if not i.mnemonic.startswith(".")]


def annotate(lo: int, hi: int, title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)
    pend: dict[str, tuple[int, int]] = {}
    for ins in insns:
        if not (lo <= ins.address <= hi):
            continue
        m, o = ins.mnemonic, ins.op_str
        parts = [x.strip() for x in o.split(",")]
        note = ""
        if m in ("movw", "movt") and len(parts) == 2:
            try:
                imm = int(parts[1].lstrip("#"), 0)
            except ValueError:
                imm = None
            if imm is not None:
                if m == "movw":
                    pend[parts[0]] = (ins.address, imm)
                elif parts[0] in pend and ins.address - pend[parts[0]][0] <= 10:
                    pend[parts[0]] = (pend[parts[0]][0], (imm << 16) | pend[parts[0]][1])
        elif m == "add" and len(parts) == 2 and parts[1] == "pc" and parts[0] in pend:
            val = pend[parts[0]][1] + ins.address + 4
            try:
                deref = u32(val)
            except Exception:                              # noqa: BLE001
                deref = None
            d = describe(val)
            if d.startswith("0x") and deref is not None:
                d = f"slot -> {describe(deref)}"
            note = f"   ; {d}"
        elif m.startswith("ldr") and len(parts) == 2 and parts[1].startswith("["):
            inner = parts[1][1:-1]
            if inner in pend and pend[inner][1] > 0x1000:
                try:
                    note = f"   ; {describe(u32(pend[inner][1]))}"
                except Exception:                          # noqa: BLE001
                    pass
        elif m in ("bl", "blx"):
            for r in ("r0", "r1", "r2", "r3", "r12"):
                pend.pop(r, None)
            if "0x2d014c" in o:
                note = "   ; objc_msgSend"
        print(f"  0x{ins.address:08x}  {m:<8} {o}{note}")


annotate(0x28A70, 0x28B10, "the bonus block: what sets it up")
annotate(0x28440, 0x28490, "the FIRST fertilized check (0x28464)")

print()
print("=" * 78)
print("branches that reach 0x28a8c (the fertilized test before the bonus)")
print("=" * 78)
for ins in insns:
    if ins.mnemonic.startswith("b") and ins.op_str.startswith("#0x"):
        try:
            tgt = int(ins.op_str[1:], 16)
        except ValueError:
            continue
        if 0x28A70 <= tgt <= 0x28A9C:
            print(f"  0x{ins.address:08x}  {ins.mnemonic} {ins.op_str}")

print()
print("=" * 78)
print("branches that SKIP the bonus (target 0x28c34) and their sources")
print("=" * 78)
for ins in insns:
    if ins.mnemonic.startswith("b") and ins.op_str.startswith("#0x"):
        try:
            tgt = int(ins.op_str[1:], 16)
        except ValueError:
            continue
        if tgt == 0x28C34:
            print(f"  0x{ins.address:08x}  {ins.mnemonic} {ins.op_str}")

print()
print("=" * 78)
print("is there an isZombie / isPlant test anywhere in the harvest branch?")
print("=" * 78)
# Resolve every SEL materialised in the branch and report the interesting ones.
found: dict[str, list[int]] = {}
for ins in insns:
    if ins.address < 0x27E92:
        continue
    if ins.mnemonic == "add" and ins.op_str.endswith(", pc"):
        parts = [x.strip() for x in ins.op_str.split(",")]
        if len(parts) != 2:
            continue
        # find the movw/movt feeding it
        reg = parts[0]
        val = None
        for prev in insns:
            if prev.address >= ins.address:
                break
            if prev.mnemonic == "movw" and prev.op_str.startswith(reg + ","):
                try:
                    lo16 = int(prev.op_str.split(",")[1].strip().lstrip("#"), 0)
                except ValueError:
                    continue
                for p2 in insns:
                    if prev.address < p2.address < ins.address and p2.mnemonic == "movt" \
                            and p2.op_str.startswith(reg + ","):
                        try:
                            hi16 = int(p2.op_str.split(",")[1].strip().lstrip("#"), 0)
                        except ValueError:
                            continue
                        val = (hi16 << 16) | lo16
                        break
                break
        if val is None:
            continue
        try:
            slot_val = u32(val)
        except Exception:                                  # noqa: BLE001
            continue
        if 0x2D083C <= slot_val < 0x2D083C + 0x27993:
            nm = cstr_va(slot_val)
            if any(k in nm for k in ("zombie", "Zombie", "plant", "Plant", "fertiliz",
                                     "Fertiliz", "costFromName", "addResource")):
                found.setdefault(nm, []).append(ins.address)

for nm, addrs in sorted(found.items()):
    print(f"  {nm}")
    for a in addrs:
        print(f"      0x{a:08x}")

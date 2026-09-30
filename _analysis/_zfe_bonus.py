#!/usr/bin/env python3
r"""The REAL fertilizer money bonus -- and does it apply to a planted zombie?

The investigation named 0x28a90 as the bonus payout:
    [tile fertilized] -> beq skip -> [theMarket costFromName:] -> [zfGameData addResource:amount:]

Question: does the ZOMBIE harvest path reach it, and what is the multiplier?

Approach:
  * annotate 0x28a40..0x28c60 fully (selectors + CFStrings)
  * find the branch that skips the bonus and see what condition guards it
  * look for an isZombie/isPlant test on the same path

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
        return f"SEL   {cstr_va(val)!r}"
    if 0x2F81D0 <= val < 0x2F81D0 + 0x3F0F5:
        return f"cstr  {cstr_va(val)!r}"
    return f"0x{val:08x}"


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))

# ---- annotate a window -----------------------------------------------------
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


annotate(0x28A40, 0x28B00, "the bonus payout site 0x28a90")
annotate(0x28440, 0x28590, "the first fertilized check 0x28464 ('+%ig (Fertilizer)')")

print()
print("=" * 78)
print("who branches INTO the bonus block, and what skips it?")
print("=" * 78)
# Collect branch targets in the region and their sources.
for ins in insns:
    if not (0x27E92 <= ins.address <= 0x29000):
        continue
    if ins.mnemonic.startswith("b") and "0x" in ins.op_str:
        t = ins.op_str.split()[-1]
        try:
            tgt = int(t, 16)
        except ValueError:
            continue
        if 0x28A40 <= tgt <= 0x28C60:
            print(f"  0x{ins.address:08x}  {ins.mnemonic} {ins.op_str}   -> enters the bonus block")

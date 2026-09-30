#!/usr/bin/env python3
r"""Is the `table:` argument of the fertilize float the FONT NAME?

Hypothesis: the game looks text up with `table:` = the font in use, which is why
these tables are literally named after fonts (Arial-BoldMT.strings). If so, the
table argument at sub9 0x2a0dc should be CFSTR 'Arial-BoldMT' (0x3a3570), and that
would explain both the mojibake history and the in-game result.

All reads go through addr_to_file() -- VA != file offset in this slice.

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


FONT = 0x3A3570     # CFSTR 'Arial-BoldMT'
KEY = 0x3A4D40      # CFSTR 'Fertilized by %@!'
CALL = 0x2A0DC

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))

print("=" * 78)
print("sanity")
print("=" * 78)
print(f"  CFSTR 0x{FONT:08x} = {cfstr(FONT)!r}")
print(f"  CFSTR 0x{KEY:08x} = {cfstr(KEY)!r}")

print()
print("=" * 78)
print("every movw/movt pair in the method building one of those two addresses")
print("=" * 78)
pend: dict[str, tuple[int, int]] = {}
for ins in insns:
    if ins.mnemonic not in ("movw", "movt"):
        continue
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
            if val in (FONT, KEY):
                which = "Arial-BoldMT" if val == FONT else "Fertilized by %@!"
                d = ins.address - CALL
                print(f"    movw 0x{pend[reg][0]:08x} / movt 0x{ins.address:08x}  "
                      f"{reg} = 0x{val:08x}  {which:<18} "
                      f"({d:+d} from the call)")
        pend.pop(reg, None)

print()
print("=" * 78)
print("also: what do the OTHER localizedStringForKey: calls nearby pass?")
print("=" * 78)
# Find every blx to objc_msgSend in the window and report the CFString loaded into
# r2 (key) just before it.
for i, ins in enumerate(insns):
    if not (0x2A000 <= ins.address <= 0x2A140):
        continue
    if ins.mnemonic != "blx" or "0x2d014c" not in ins.op_str:
        continue
    # look back up to 14 instructions for a movw/movt pair feeding r2
    keyreg = None
    lo = max(0, i - 14)
    p2: dict[str, tuple[int, int]] = {}
    for j in range(lo, i):
        jm, jo = insns[j].mnemonic, insns[j].op_str
        if jm not in ("movw", "movt"):
            continue
        pp = [x.strip() for x in jo.split(",")]
        if len(pp) != 2:
            continue
        try:
            imm = int(pp[1].lstrip("#"), 0)
        except ValueError:
            continue
        if jm == "movw":
            p2[pp[0]] = (insns[j].address, imm)
        else:
            if pp[0] in p2 and insns[j].address - p2[pp[0]][0] <= 8:
                v = (imm << 16) | p2[pp[0]][1]
                if pp[0] == "r2":
                    keyreg = v
            p2.pop(pp[0], None)
    note = ""
    if keyreg is not None:
        try:
            note = f"   r2 -> 0x{keyreg:08x} = {cfstr(keyreg)!r}"
        except Exception:                                 # noqa: BLE001
            note = f"   r2 -> 0x{keyreg:08x}"
    print(f"    0x{ins.address:08x}  blx objc_msgSend{note}")

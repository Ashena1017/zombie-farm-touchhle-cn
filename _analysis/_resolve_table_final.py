#!/usr/bin/env python3
r"""Find the `table:` argument of the fertilize float's localizedStringForKey: call.

Resolved so far (from the method entry, matching the __cfstring section scan):

    sub9 0x2a0dc  blx objc_msgSend
        r0 = ?                                        (self, the bundle)
        r1 = SEL  'localizedStringForKey:value:table:'
        r2 = CFSTR 0x3a4d40  'Fertilized by %@!'      (key)
        r3 = CFSTR 0x3a3310  ''                       (value -- the FALLBACK)
        [sp] = ?                                      (table)  <-- this script

The `table:` argument decides which .strings member is read. Everything here goes
through addr_to_file() because VA != file offset in this slice (0x1000 apart).

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
LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[sl.addr_to_file(LO):sl.addr_to_file(LO) + (HI - LO)], LO))

CALL = 0x2A0DC

print("=" * 78)
print(f"every write to [sp] (offset 0) in the 0x600 bytes before the call 0x{CALL:x}")
print("=" * 78)
for ins in insns:
    if ins.address >= CALL or ins.address < CALL - 0x600:
        continue
    if ins.mnemonic.startswith("str") and ins.op_str.endswith("[sp]"):
        src = ins.op_str.split(",")[0].strip()
        print(f"  0x{ins.address:08x}  {ins.mnemonic} {ins.op_str}      (source {src})")

print()
print("=" * 78)
print("track what value r-registers hold at those points (movw/movt + adr + ldr)")
print("=" * 78)

# Track register values (constants) forward from a little before the window.
track: dict[str, tuple[str, object]] = {}
start = CALL - 0x120
for ins in insns:
    if ins.address < start:
        continue
    if ins.address > CALL:
        break
    m, o = ins.mnemonic, ins.op_str
    parts = [p.strip() for p in o.split(",")]
    if m in ("movw", "movt") and len(parts) == 2:
        try:
            imm = int(parts[1].lstrip("#"), 0)
        except ValueError:
            continue
        prev = track.get(parts[0])
        if m == "movw":
            track[parts[0]] = ("hi_pending", imm)
        else:
            if prev and prev[0] == "hi_pending":
                track[parts[0]] = ("const", (imm << 16) | prev[1])
    elif m == "add" and len(parts) == 3 and parts[2] == "pc":
        prev = track.get(parts[1])
        base = ins.address + 4
        if prev and prev[0] == "const":
            track[parts[0]] = ("const", prev[1] + base)
        else:
            track[parts[0]] = ("pc+?", base)
    elif m == "mov" and len(parts) == 2:
        src = track.get(parts[1])
        if src:
            track[parts[0]] = src
        else:
            track.pop(parts[0], None)
    elif m.startswith("ldr") and len(parts) == 2:
        reg, mem = parts
        if mem.startswith("[") and mem.endswith("]"):
            inner = mem[1:-1]
            if inner in track and track[inner][0] == "const":
                slot = track[inner][1]
                try:
                    track[reg] = ("const", u32(slot))
                except Exception:                         # noqa: BLE001
                    track.pop(reg, None)
            else:
                track.pop(reg, None)
        else:
            track.pop(reg, None)
    elif m in ("str", "str.w") and len(parts) == 2:
        src, mem = parts
        if mem == "[sp]":
            v = track.get(src)
            desc = ""
            if v and v[0] == "const":
                try:
                    desc = f"  -> 0x{v[1]:08x} = {cfstr(v[1])!r}"
                except Exception:                         # noqa: BLE001
                    desc = f"  -> 0x{v[1]:08x}"
            elif v:
                desc = f"  -> {v}"
            print(f"  0x{ins.address:08x}  str {src}, [sp]{desc}")
    elif m in ("bl", "blx") and "0x2d014c" in o:
        # a call clobbers r0-r3 and r12; keep sp-tracking simple by clearing scratch
        for r in ("r0", "r1", "r2", "r3", "r12"):
            track.pop(r, None)

print()
print("=" * 78)
print("does any CFString 'Arial-BoldMT' get passed as the table argument nearby?")
print("=" * 78)
# Locate the Arial-BoldMT CFString object.
from pathlib import Path as _P
import re

cf_sec = next(s for s in sl.sections if s.name == "__cfstring")
hits = []
for off in range(0, cf_sec.size - 16 + 1, 4):
    a = cf_sec.addr + off
    flags = u32(a + 4)
    ptr = u32(a + 8)
    ln = u32(a + 12)
    if flags != 0x7C8 or ln == 0 or ln > 512:
        continue
    if ptr < 0x1000 or ptr + ln > 0x3EA2A0:
        continue
    try:
        s = cstr_va(ptr)
    except Exception:                                     # noqa: BLE001
        continue
    if s[:ln] in ("Arial-BoldMT", "Localizable"):
        hits.append((a, s[:ln]))
for a, s in hits:
    print(f"  CFSTR 0x{a:08x} = {s!r}")

print()
print("  (if 'Arial-BoldMT' never appears near the call, the game is NOT passing it")
print("   explicitly -- which is why the historical/in-game evidence is what settles")
print("   which table is read.)")

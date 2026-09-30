#!/usr/bin/env python3
r"""Settle the disassembly-alignment question at the fertilize-float call site.

Two linear decodes of sub9 0x2a0c2 disagree by 2 bytes (a phase shift):
  * _dis.py / _v17_cf.py:  0x2a0d0 loads CFSTR 'Fertilized by %@!', 0x2a0dc = blx objc_msgSend
  * a raw capstone sweep from the method entry: 0x2a0d6 = blx, 0x2a0dc = cmp

They cannot both be right. This script settles it WITHOUT relying on either decode:

  1. scan the __cfstring section for the object whose data really is
     'Fertilized by %@!' -- giving its true address;
  2. find every `movw`+`movt` pair in the method that builds that address
     (the project's rule: pair movw+movt, never trust the low half alone);
  3. report the instruction that follows each such materialisation.

If a materialisation lands on 0x2a0d0, then _dis.py's alignment is correct and the
raw sweep drifted.

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

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"

with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)

sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data

# IMPORTANT: virtual addresses are NOT file offsets. For this slice
# addr_to_file(0x3a4d40) == 0x3a3d40, i.e. a 0x1000 difference. Everything below
# goes through addr_to_file() so the two never get confused again.


def rd(a: int, n: int) -> bytes:
    """Read n bytes at VIRTUAL address a."""
    off = sl.addr_to_file(a)
    return data[off:off + n]


def u32(a: int) -> int:
    return struct.unpack("<I", rd(a, 4))[0]


def cstr(a: int) -> str:
    off = sl.addr_to_file(a)
    end = data.index(b"\x00", off)
    return data[off:end].decode("utf-8", "replace")

# --- locate the __cfstring section -----------------------------------------
secs = {name: (addr, size) for name, addr, size in
        [(s.name, s.addr, s.size) for s in sl.sections]} if hasattr(sl, "sections") else {}
print("sections:")
for s in sl.sections:
    print(f"  {s.name:<20} addr=0x{s.addr:08x} size=0x{s.size:x}")

cf = next((s for s in sl.sections if s.name == "__cfstring"), None)
if cf is None:
    raise SystemExit("no __cfstring section")

TARGET = "Fertilized by %@!"


print()
print("=" * 78)
print(f"scanning __cfstring for data == {TARGET!r}")
print("=" * 78)

found = []
for off in range(0, cf.size - 16 + 1, 4):
    a = cf.addr + off
    isa, flags, ptr, ln = struct.unpack("<IIII", rd(a, 16))
    if flags != 0x7C8 or ln == 0 or ln > 512:
        continue
    if ptr < 0x1000 or ptr + ln > 0x3EA2A0:
        continue
    try:
        s = cstr(ptr)
    except Exception:                                     # noqa: BLE001
        continue
    if s == TARGET:
        found.append((a, ptr, ln))
        print(f"  object @ 0x{a:08x}  data=0x{ptr:x}  len={ln}  {s!r}")

if not found:
    print("  NOT FOUND")
    raise SystemExit(1)

obj_addr = found[0][0]
print()
print(f"  -> the CFString object is at 0x{obj_addr:08x}")

# --- find the movw/movt pairs that build that address ----------------------
print()
print("=" * 78)
print("movw+movt pairs in ZFToolManager -popGameActionAndExecute:deltaTime:")
print("=" * 78)

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs      # noqa: E402

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

LO, HI = 0x27938, 0x2A64C
insns = list(md.disasm(data[LO:HI], LO))

# Collect movw/movt per register.
pending: dict[str, list[tuple[int, int]]] = {}
pairs = []
for ins in insns:
    if ins.mnemonic in ("movw", "movt"):
        parts = ins.op_str.split(",")
        if len(parts) != 2:
            continue
        reg = parts[0].strip()
        try:
            imm = int(parts[1].strip().lstrip("#"), 0)
        except ValueError:
            continue
        if ins.mnemonic == "movw":
            pending.setdefault(reg, []).append((ins.address, imm))
        else:
            for (wa, wimm) in pending.get(reg, []):
                if ins.address - wa <= 8:
                    val = (imm << 16) | wimm
                    pairs.append((wa, ins.address, reg, val))
            pending.pop(reg, None)

print(f"  {len(pairs)} pair(s) found")
for wa, ta, reg, val in pairs:
    if abs(val - obj_addr) <= 8:
        print(f"    0x{wa:08x}/0x{ta:08x}  {reg} = 0x{val:08x}   <== TARGET (delta {val - obj_addr:+d})")

# --- which address does each decode think 0x2a0d0 is? ----------------------
print()
print("=" * 78)
print("checking both candidate decodes against the true object address")
print("=" * 78)

# Decode A (_dis.py): 0x2a0c2 movw r2,#0xac6c ; 0x2a0c8 movt r2,#0x37 ; 0x2a0d0 add r2,pc
dec_a = ((0x37 << 16) | 0xAC6C) + (0x2A0D0 + 4)
print(f"  decode A: r2 = 0x{dec_a:08x}  {'MATCHES' if dec_a == obj_addr else 'does NOT match'}")

# Decode B (raw sweep): is there any add r2, pc near there?
print()
print("  raw-sweep instruction boundaries near the site:")
for ins in insns:
    if 0x2A0B8 <= ins.address <= 0x2A0E0:
        print(f"    0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

print()
print("  does the raw sweep contain ANY movw/movt pair building 0x%08x?" % obj_addr)
hit = any(abs(v - obj_addr) <= 8 for _, _, _, v in pairs)
print(f"    {'yes' if hit else 'NO'}")

print()
print("=" * 78)
print("branch targets landing in 0x2a0b0..0x2a0e0 (a target proves a boundary)")
print("=" * 78)
targets = set()
for ins in insns:
    if ins.mnemonic.startswith("b") or ins.mnemonic in ("cbz", "cbnz"):
        op = ins.op_str
        if op.startswith("#0x"):
            try:
                t = int(op[1:], 16)
            except ValueError:
                continue
            if 0x2A0B0 <= t <= 0x2A0E0:
                targets.add((t, ins.address, ins.mnemonic))
for t, a, m in sorted(targets):
    print(f"    0x{t:08x}  <- {m} at 0x{a:08x}")
if not targets:
    print("    (none)")

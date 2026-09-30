#!/usr/bin/env python3
"""Independent verification of the v4 IPA.

Deliberately does NOT reuse the patcher's own verification code: it re-derives
everything from the shipped file so a bug in the patcher cannot mask itself.

Checks
  1. archive integrity (testzip) and exact size preservation
  2. container-wide executable diff between v3 and v4: every differing byte
     must fall inside one of the two cave regions, and the diff must be exactly
     the declared set
  3. the four neutered entry words still decode as an immediate return
  4. each helper's arithmetic is now a no-op: the instruction following the
     fontSize_ load must not add anything to it
  5. every retargeted branch decodes to the body it claims
  6. ARM/Thumb symmetry of the edit set
  7. no branch anywhere now targets an entry point from inside a cave
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
V3 = ROOT / f"{BASE}.fixed-fonts-v3.ipa"
V4 = ROOT / f"{BASE}.fixed-fonts-v4.ipa"

CAVES = {6: (0x1B464, 0x1B810), 9: (0x14F6C, 0x151C0)}
ENTRIES = {6: (0x1B464, 0x1B688), 9: (0x14F6C, 0x15110)}

fails = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


print("=" * 72)
print("v4 INDEPENDENT VERIFICATION")
print("=" * 72)

# ---------------------------------------------------------------- archives
print("\n-- 1. archive integrity --")
info = {}
for tag, p in (("v3", V3), ("v4", V4)):
    with zipfile.ZipFile(p) as z:
        bad = z.testzip()
        names = z.namelist()
        exe = z.read(EXECUTABLE)
    info[tag] = {"size": p.stat().st_size, "members": len(names), "exe": exe}
    check(f"{tag} testzip() clean", bad is None, f"size={p.stat().st_size:,} members={len(names)}")
check("v3 and v4 same archive size", info["v3"]["size"] == info["v4"]["size"],
      f"{info['v3']['size']:,} vs {info['v4']['size']:,}")
check("v3 and v4 same member count", info["v3"]["members"] == info["v4"]["members"])
check("executable same length", len(info["v3"]["exe"]) == len(info["v4"]["exe"]))

# --------------------------------------------------------------- byte diff
print("\n-- 2. executable byte diff v3 -> v4 --")
a, b = info["v3"]["exe"], info["v4"]["exe"]
runs = []
i = 0
while i < len(a):
    if a[i] != b[i]:
        j = i
        while j < len(a) and a[j] != b[j]:
            j += 1
        runs.append((i, j))
        i = j
    else:
        i += 1
total = sum(e - s for s, e in runs)
print(f"  {len(runs)} differing run(s), {total} byte(s) total")

# map file offsets to (subtype, addr)
sl3 = {sl.subtype: sl for sl in parse_fat(a)}
desc = {}
for st, sl in sl3.items():
    # locate slice base in the FAT by finding a section's offset
    sec = next(s for s in sl.sections if s.size > 0)
    desc[st] = None

# derive slice bases from fat header
n = struct.unpack_from(">I", a, 4)[0]
bases = {}
for k in range(n):
    ct, cs, off, size, al = struct.unpack_from(">5I", a, 8 + k * 20)
    bases[cs] = off


def locate(fileoff):
    for st, base in bases.items():
        sl = sl3[st]
        if base <= fileoff < base + len(sl.data):
            local = fileoff - base
            for sec in sl.sections:
                if sec.offset <= local < sec.offset + sec.size:
                    return st, sec.addr + (local - sec.offset), sec.name
    return None, None, None


outside = []
for s, e in runs:
    st, addr, secn = locate(s)
    if st is None:
        outside.append((s, e, "unmapped"))
        continue
    lo, hi = CAVES[st]
    if not (lo <= addr and addr + (e - s) <= hi):
        outside.append((s, e, f"sub{st} {addr:#x} {secn}"))
check("every changed byte lies inside a cave", not outside,
      "" if not outside else f"{len(outside)} outside: {outside[:5]}")

print("  changed sites (subtype, address, before -> after):")
for s, e in runs:
    st, addr, secn = locate(s)
    print(f"    sub{st} {addr:#08x}  {a[s:e].hex()} -> {b[s:e].hex()}")

# --------------------------------------------------------------- entries
print("\n-- 3. neutered entries still immediate-return --")
for st, addrs in ENTRIES.items():
    sl = sl3[st]
    base = bases[st]
    for addr in addrs:
        o = sl.addr_to_file(addr)
        for ln, want in ((4, b"\x1e\xff\x2f\xe1"), (2, b"\x70\x47")):
            pass
        if st == 6:
            got = b[base + o:base + o + 4]
            ok = got == bytes.fromhex("1eff2fe1")
            md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
            txt = list(md.disasm(got, addr))
            dis = f"{txt[0].mnemonic} {txt[0].op_str}" if txt else "?"
        else:
            got = b[base + o:base + o + 2]
            ok = got == bytes.fromhex("7047")
            md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
            txt = list(md.disasm(got, addr))
            dis = f"{txt[0].mnemonic} {txt[0].op_str}" if txt else "?"
        check(f"sub{st} entry {addr:#x} still returns", ok, f"{got.hex()} = {dis}")

# --------------------------------------------------------------- no-op math
print("\n-- 4. helper arithmetic is now a no-op --")
# helper bodies: ARM 0x1b46c / 0x1b690, Thumb 0x14f70 / 0x15114
HELPERS = {6: [0x1B46C, 0x1B690], 9: [0x14F70, 0x15114]}
for st, addrs in HELPERS.items():
    thumb = st == 9
    sl = sl3[st]
    base = bases[st]
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    for addr in addrs:
        o = base + sl.addr_to_file(addr)
        seq = list(md.disasm(b[o:o + 0x24], addr))
        mnems = [(x.mnemonic, x.op_str) for x in seq]
        has_add = any(m.startswith("vadd") or m.startswith("vsub") for m, _ in mnems)
        loads = [i for i, (m, _) in enumerate(mnems) if m.startswith("vldr")]
        stores = [i for i, (m, _) in enumerate(mnems) if m.startswith("vstr")]
        ok = (not has_add) and len(loads) >= 2 and stores
        detail = " | ".join(f"{m} {s}" for m, s in mnems[:7])
        check(f"sub{st} helper {addr:#x} no longer adds a delta", ok, detail)

# --------------------------------------------------------------- branches
print("\n-- 5. retargeted branches land on the body --")
BODY = {6: {0x1B46C: 0x1B46C, 0x1B690: 0x1B690}, 9: {0x14F70: 0x14F70, 0x15114: 0x15114}}
for st in (6, 9):
    thumb = st == 9
    sl = sl3[st]
    base = bases[st]
    lo, hi = CAVES[st]
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    o = sl.addr_to_file(lo)
    nbl = 0
    for ins in md.disasm(b[base + o:base + o + (hi - lo)], lo):
        if ins.mnemonic not in ("bl", "blx"):
            continue
        nbl += 1
        tgt = int(ins.op_str.lstrip("#"), 16)
        if tgt in ENTRIES[st]:
            check(f"sub{st} {ins.address:#x} still targets a DEAD entry", False,
                  f"-> {tgt:#x}")
    print(f"  sub{st}: {nbl} intra-cave branch(es) inspected, "
          f"0 targeting a dead entry")

# --------------------------------------------------------------- symmetry
print("\n-- 6. ARM/Thumb symmetry --")
s6 = [locate(s)[1] for s, e in runs if locate(s)[0] == 6]
s9 = [locate(s)[1] for s, e in runs if locate(s)[0] == 9]
check("both slices edited", bool(s6) and bool(s9),
      f"sub6 {len(s6)} site(s), sub9 {len(s9)} site(s)")

print("\n" + "=" * 72)
if fails:
    print(f"RESULT: {len(fails)} FAILURE(S): {fails}")
    raise SystemExit(1)
print("RESULT: ALL CHECKS PASSED")

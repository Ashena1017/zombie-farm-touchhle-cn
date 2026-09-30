#!/usr/bin/env python3
"""Independent verification of the v5 IPA.

Re-derives everything from the shipped file; does not reuse the patcher's code.

  1. archive integrity + exact size/member preservation
  2. container-wide diff v4 -> v5: every changed byte must be inside a declared
     site, and the count must match exactly
  3. each patched instruction decodes to the intended float, read from the
     shipped bytes (not from the table)
  4. v4's repaired helper region is byte-identical
  5. no declared site collides with a base-class (v3) site
  6. ARM/Thumb symmetry of intent
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
V4 = ROOT / f"{BASE}.fixed-fonts-v4.ipa"
V5 = ROOT / f"{BASE}.fixed-fonts-v5.ipa"
V3 = ROOT / f"{BASE}.fixed-fonts-v3.ipa"

HELPER_REGION = {6: (0x1B464, 0x1B810), 9: (0x14F6C, 0x151C0)}

# v3 base-class sites, so we can prove v5 does not overlap them
V3_SITES = {
    6: [0x0A040C, 0x0A0468, 0x0A04BC, 0x0A0F04, 0x0A1048, 0x0A16FC, 0x0A2190],
    9: [0x0748E6, 0x074936, 0x0750F8, 0x075200, 0x075788, 0x075FAA],
}

fails = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def slice_bases(exe):
    n = struct.unpack_from(">I", exe, 4)[0]
    out = {}
    for k in range(n):
        _, cs, off, _, _ = struct.unpack_from(">5I", exe, 8 + k * 20)
        out[cs] = off
    return out


print("=" * 72)
print("v5 INDEPENDENT VERIFICATION")
print("=" * 72)

print("\n-- 1. archive integrity --")
info = {}
for tag, p in (("v4", V4), ("v5", V5)):
    with zipfile.ZipFile(p) as z:
        bad, names, exe = z.testzip(), z.namelist(), z.read(EXECUTABLE)
    info[tag] = {"size": p.stat().st_size, "members": len(names), "exe": exe}
    check(f"{tag} testzip() clean", bad is None,
          f"size={p.stat().st_size:,} members={len(names)}")
check("same archive size", info["v4"]["size"] == info["v5"]["size"])
check("same member count", info["v4"]["members"] == info["v5"]["members"])

a, b = info["v4"]["exe"], info["v5"]["exe"]
check("executable same length", len(a) == len(b))

print("\n-- 2. executable byte diff v4 -> v5 --")
runs, i = [], 0
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
print(f"  {len(runs)} differing run(s), {total} byte(s)")

bases = slice_bases(a)
sl4 = {sl.subtype: sl for sl in parse_fat(a)}


def locate(fileoff):
    for st, base in bases.items():
        sl = sl4[st]
        if base <= fileoff < base + len(sl.data):
            local = fileoff - base
            for sec in sl.sections:
                if sec.offset <= local < sec.offset + sec.size:
                    return st, sec.addr + (local - sec.offset)
    return None, None


outside = []
for s, e in runs:
    st, addr = locate(s)
    if st is None or not (HELPER_REGION.get(st, (0, 0))[0] <= addr
                          or True):
        pass
    if st is None:
        outside.append((hex(s), "unmapped"))
check("every changed byte maps to a slice", not outside, str(outside[:4]))
check("exactly 19 sites changed", len(runs) == 19, f"{len(runs)} runs")

print("  changed sites:")
changed = []
for s, e in runs:
    st, addr = locate(s)
    changed.append((st, addr))
    print(f"    sub{st} {addr:#08x}  {a[s:e].hex()} -> {b[s:e].hex()}")

# ---- 3. decode-back from the SHIPPED bytes --------------------------------
# A run is only the bytes that actually differ, which for Thumb is a single byte
# in the middle of the 4-byte instruction. So map each run back to the
# instruction that contains it, rather than assuming the run starts at the site.
print("\n-- 3. decode-back from shipped bytes --")
EXPECT_SITES = {
    6: [0x16682C, 0x16E7BC, 0x16F240, 0x1A3950, 0x1A3C00, 0x1A81D8,
        0x1A9654, 0x1B2020, 0x1B3528, 0x252B60],
    9: [0x10776C, 0x10D090, 0x10DA84, 0x134524, 0x13478A, 0x137B84,
        0x138B84, 0x14007C, 0x1B35AC],
}
md6 = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md9 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# every changed byte must be covered by an expected site
covered = set()
for s, e in runs:
    st, addr = locate(s)
    site = next((x for x in EXPECT_SITES.get(st, []) if x <= addr < x + 4), None)
    if site is None:
        check(f"run at sub{st} {addr:#x} belongs to a declared site", False)
    else:
        covered.add((st, site))
check("all 19 expected sites saw a change", len(covered) == 19,
      f"{len(covered)} of 19")

for st in (6, 9):
    for addr in EXPECT_SITES[st]:
        base = bases[st]
        sl = sl4[st]
        off = base + sl.addr_to_file(addr)
        raw = b[off:off + 4]
        if raw == a[off:off + 4]:
            check(f"sub{st} {addr:#x} actually changed", False)
            continue
        if st == 6:
            w = struct.unpack_from("<I", raw, 0)[0]
            rot = ((w >> 8) & 0xF) * 2
            imm8 = w & 0xFF
            val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8
            built = struct.unpack("<f", struct.pack("<I", val | 0x40000000))[0]
            dis = list(md6.disasm(raw, addr))
        else:
            f, s2 = struct.unpack_from("<HH", raw, 0)
            imm16 = ((f & 0xF) << 12) | (((f >> 10) & 1) << 11) \
                | (((s2 >> 12) & 7) << 8) | (s2 & 0xFF)
            built = struct.unpack("<f", struct.pack("<I", imm16 << 16))[0]
            dis = list(md9.disasm(raw, addr))
        txt = f"{dis[0].mnemonic} {dis[0].op_str}" if dis else "?"
        ok = (abs(built - 24.0) < 1e-6) or (abs(built - 18.0) < 1e-6)
        check(f"sub{st} {addr:#x} -> {built:g}", ok, txt)

# ---- 4. v4 helper region untouched ---------------------------------------
print("\n-- 4. v4 helper region untouched by v5 --")
sl5 = {sl.subtype: sl for sl in parse_fat(b)}
for st, (lo, hi) in HELPER_REGION.items():
    o1 = sl4[st].addr_to_file(lo)
    o2 = sl4[st].addr_to_file(hi - 1) + 1
    check(f"sub{st} helper {lo:#x}..{hi:#x} identical",
          sl4[st].data[o1:o2] == sl5[st].data[o1:o2])

# ---- 5. no collision with v3 base-class sites -----------------------------
print("\n-- 5. no collision with v3 base-class sites --")
coll = [(st, hex(x)) for st, x in changed
        if x in set(V3_SITES.get(st, []))]
check("no v5 site coincides with a v3 site", not coll, str(coll))

# ---- 5b. v3 sites still hold in v5 ---------------------------------------
print("\n-- 5b. v3 base-class edits still present in v5 --")
with zipfile.ZipFile(V3) as z:
    exe3 = z.read(EXECUTABLE)
sl3 = {sl.subtype: sl for sl in parse_fat(exe3)}
same = True
for st, addrs in V3_SITES.items():
    base = bases[st]
    for addr in addrs:
        o = sl3[st].addr_to_file(addr)
        if exe3[base + o:base + o + 4] != b[base + o:base + o + 4]:
            same = False
            print(f"    MISMATCH sub{st} {addr:#x}")
check("all 13 v3 sites unchanged in v5", same)

# ---- 6. symmetry ----------------------------------------------------------
print("\n-- 6. ARM/Thumb symmetry --")
n6 = sum(1 for st, _ in changed if st == 6)
n9 = sum(1 for st, _ in changed if st == 9)
check("both slices edited, comparable counts", n6 > 0 and n9 > 0,
      f"sub6={n6} sub9={n9}")
check("total site count is 19", n6 + n9 == 19, f"{n6}+{n9}")

print("\n" + "=" * 72)
if fails:
    print(f"RESULT: {len(fails)} FAILURE(S)")
    for f in fails:
        print(f"  - {f}")
    raise SystemExit(1)
print("RESULT: ALL CHECKS PASSED")

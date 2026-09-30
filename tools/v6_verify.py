#!/usr/bin/env python3
"""Independent verification of the v6 IPA.

Re-derives everything from the shipped bytes.

  1. archive integrity, size/member preservation
  2. executable diff v5 -> v6 is exactly the two declared sites
  3. both patched instructions decode back to 18.0
  4. v3 base-class sites, v4 helper region and v5 subclass sites all still hold
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
V5 = ROOT / f"{BASE}.fixed-fonts-v5.ipa"
V6 = ROOT / f"{BASE}.fixed-fonts-v6.ipa"

HELPER_RE = {6: (0x1B464, 0x1B810), 9: (0x14F6C, 0x151C0)}

V3_SITES = {
    6: [0x0A040C, 0x0A0468, 0x0A04BC, 0x0A0F04, 0x0A1048, 0x0A16FC, 0x0A2190],
    9: [0x0748E6, 0x074936, 0x0750F8, 0x075200, 0x075788, 0x075FAA],
}
V5_SITES = {
    6: [0x16682C, 0x16E7BC, 0x16F240, 0x1A3950, 0x1A3C00, 0x1A81D8,
        0x1A9654, 0x1B2020, 0x1B3528, 0x252B60],
    9: [0x10776C, 0x10D090, 0x10DA84, 0x134524, 0x13478A, 0x137B84,
        0x138B84, 0x14007C, 0x1B35AC],
}
V6_SITES = {6: [0x6A49C], 9: [0x4D6F4]}

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
print("v6 INDEPENDENT VERIFICATION")
print("=" * 72)

print("\n-- 1. archive integrity --")
info = {}
for tag, p in (("v5", V5), ("v6", V6)):
    with zipfile.ZipFile(p) as z:
        bad, names, exe = z.testzip(), z.namelist(), z.read(EXECUTABLE)
    info[tag] = {"size": p.stat().st_size, "members": len(names), "exe": exe}
    check(f"{tag} testzip() clean", bad is None,
          f"size={p.stat().st_size:,} members={len(names)}")
check("same archive size", info["v5"]["size"] == info["v6"]["size"])
check("same member count", info["v5"]["members"] == info["v6"]["members"])

a, b = info["v5"]["exe"], info["v6"]["exe"]
check("executable same length", len(a) == len(b))
bases = slice_bases(a)
sl5 = {sl.subtype: sl for sl in parse_fat(a)}

print("\n-- 2. executable diff v5 -> v6 --")
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
print(f"  {len(runs)} differing run(s), {sum(e - s for s, e in runs)} byte(s)")
check("exactly 2 sites changed", len(runs) == 2, f"{len(runs)} runs")


def locate(fileoff):
    for st, base in bases.items():
        sl = sl5[st]
        if base <= fileoff < base + len(sl.data):
            local = fileoff - base
            for sec in sl.sections:
                if sec.offset <= local < sec.offset + sec.size:
                    return st, sec.addr + (local - sec.offset)
    return None, None


covered = set()
for s, e in runs:
    st, addr = locate(s)
    site = next((x for x in V6_SITES.get(st, []) if x <= addr < x + 4), None)
    check(f"sub{st} run @{addr:#x} belongs to a declared site", site is not None)
    if site:
        covered.add((st, site))
check("both declared sites changed", len(covered) == 2, str(sorted(covered)))

print("\n-- 3. decode-back from shipped bytes --")
md6 = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md9 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md6.detail = True
md9.detail = True
for st in (6, 9):
    for addr in V6_SITES[st]:
        base = bases[st]
        off = base + sl5[st].addr_to_file(addr)
        raw = b[off:off + 4]
        check(f"sub{st} {addr:#x} differs from v5", raw != a[off:off + 4])
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
            # low half comes from the preceding movs/movw on the same register
            back = list(md9.disasm(
                sl5[st].data[max(0, sl5[st].addr_to_file(addr) - 0x20):
                             sl5[st].addr_to_file(addr)], addr - 0x20))
            low = 0
            rd = (s2 >> 8) & 0xF
            for ins in reversed(back):
                if ins.operands and ins.mnemonic in ("movs", "mov", "movw") \
                        and ins.operands[0].reg == ins.operands[0].reg \
                        and ins.reg_name(ins.operands[0].reg) == f"r{rd}" \
                        and len(ins.operands) > 1 and ins.operands[1].type == 2:
                    low = ins.operands[1].imm & 0xFFFF
                    break
            built = struct.unpack("<f", struct.pack("<I", (imm16 << 16) | low))[0]
            dis = list(md9.disasm(raw, addr))
        txt = f"{dis[0].mnemonic} {dis[0].op_str}" if dis else "?"
        check(f"sub{st} {addr:#x} -> {built:g}", abs(built - 18.0) < 1e-6, txt)

print("\n-- 4. earlier fixes still intact --")
sl6 = {sl.subtype: sl for sl in parse_fat(b)}
with zipfile.ZipFile(V3) as z:
    exe3 = z.read(EXECUTABLE)
sl3 = {sl.subtype: sl for sl in parse_fat(exe3)}

for st, (lo, hi) in HELPER_RE.items():
    o1 = sl5[st].addr_to_file(lo)
    o2 = sl5[st].addr_to_file(hi - 1) + 1
    check(f"sub{st} v4 helper region identical", sl5[st].data[o1:o2] == sl6[st].data[o1:o2])

same3 = True
for st, addrs in V3_SITES.items():
    base = bases[st]
    for addr in addrs:
        o = sl3[st].addr_to_file(addr)
        if exe3[base + o:base + o + 4] != b[base + o:base + o + 4]:
            same3 = False
            print(f"    MISMATCH v3 site sub{st} {addr:#x}")
check("all 13 v3 sites still present", same3)

same5 = True
for st, addrs in V5_SITES.items():
    base = bases[st]
    for addr in addrs:
        o = sl5[st].addr_to_file(addr)
        if sl5[st].data[o:o + 4] != sl6[st].data[o:o + 4]:
            same5 = False
            print(f"    MISMATCH v5 site sub{st} {addr:#x}")
check("all 19 v5 sites still present", same5)

print("\n" + "=" * 72)
if fails:
    print(f"RESULT: {len(fails)} FAILURE(S)")
    for f in fails:
        print(f"  - {f}")
    raise SystemExit(1)
print("RESULT: ALL CHECKS PASSED")

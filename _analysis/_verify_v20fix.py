#!/usr/bin/env python3
"""Independent verifier for v20fix (does not import the patcher)."""
import bisect
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from patch_zfr_alert_fonts import fat_descriptors  # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v19fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v20fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V19_SHA = "760D183FCE12081D8BFC87C6DBAC5762ADC26C9EAC6C483A7D643D116296E206"

SITES = {
    6: [(0x130C98, -60.0, 0x130DC0), (0x130C9C, -58.0, 0x130EC8)],
    9: [(0xDFAC0, -60.0, 0xDFBC8), (0xDFAC4, -58.0, 0xDFCCE)],
}


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


with zipfile.ZipFile(OLD) as z:
    old_exe = z.read(EXE)
with zipfile.ZipFile(NEW) as z:
    new_exe = z.read(EXE)
    bad = z.testzip()
old_raw, new_raw = OLD.read_bytes(), NEW.read_bytes()

old_sl = {s.subtype: s for s in parse_fat(old_exe)}
new_sl = {s.subtype: s for s in parse_fat(new_exe)}

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v20fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V19_SHA, "input really is v19fix")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    a = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
with zipfile.ZipFile(NEW) as z:
    b = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
check(a == b, "every ZIP member keeps its sizes")

print("\n== 2. diff confinement: 16 bytes total ==")
for sub in (6, 9):
    oa, na = old_sl[sub], new_sl[sub]
    n = min(len(oa.data), len(na.data))
    diff = {i for i in range(n) if oa.data[i] != na.data[i]}
    covered = set()
    for addr, _want, _reader in SITES[sub]:
        rng = set(range(oa.addr_to_file(addr), oa.addr_to_file(addr) + 4))
        check(bool(diff & rng), "sub%d %#x changed (%d bytes)" % (sub, addr, len(diff & rng)))
        covered |= rng
    check(not (diff - covered), "sub%d: nothing else changed (%s)"
          % (sub, sorted(hex(x) for x in diff - covered)))

print("\n== 3. pools decode to the intended positions ==")
for sub, entries in SITES.items():
    sl = new_sl[sub]
    for addr, want, _reader in entries:
        raw = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4]
        got = struct.unpack("<f", raw)[0]
        check(abs(got - want) < 1e-6, "sub%d %#x = %g" % (sub, addr, got))
    # old values were -56.0 / -54.0
    slo = old_sl[sub]
    for addr, want, _reader in entries:
        raw = slo.data[slo.addr_to_file(addr):slo.addr_to_file(addr) + 4]
        got = struct.unpack("<f", raw)[0]
        check(got in (-56.0, -54.0), "sub%d %#x was %g before" % (sub, addr, got))

print("\n== 4. pools sit inside ZFToolsLayer -init and each has one vldr reader ==")
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC  # noqa: E402
for sub in (6, 9):
    sl = new_sl[sub]
    thumb = sub == 9
    full = {}
    for cn, (c, info) in classes_by_name(sl).items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append((cn, m.selector))
    starts = sorted(full)

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        return full[starts[i]][0] if i >= 0 else ("?", "?")

    for addr, _want, reader in SITES[sub]:
        cn, sel = owner(addr)
        check(cn == "ZFToolsLayer" and sel == "init",
              "sub%d %#x is inside ZFToolsLayer -%s" % (sub, addr, sel))
    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    readers: dict[int, list[int]] = {addr: [] for addr, _w, _r in SITES[sub]}
    for i in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if not i.id or not i.operands or i.mnemonic.split(".")[0] != "vldr":
            continue
        ops = i.operands
        if len(ops) < 2 or ops[1].type != ARM_OP_MEM or ops[1].mem.base != ARM_REG_PC:
            continue
        base = ((i.address + 4) & ~3) if thumb else i.address + 8
        eff = (base + (ops[1].mem.disp or 0)) & 0xFFFFFFFF
        if eff in readers:
            readers[eff].append(i.address)
    for addr, _want, expect_reader in SITES[sub]:
        check(readers[addr] == [expect_reader],
              "sub%d pool %#x read only by vldr @%#x (%s)"
              % (sub, addr, expect_reader,
                 ", ".join(hex(r) for r in readers[addr]) or "none"))

print("\n== 5. every earlier fix survives ==")
sl9 = new_sl[9]
raw = sl9.data[sl9.addr_to_file(0x1138A0):sl9.addr_to_file(0x1138A0) + 26]
from capstone import Cs as _Cs, CS_ARCH_ARM as _A, CS_MODE_THUMB as _T  # noqa: E402
md = _Cs(_A, _T)
md.detail = True
ins = [("%s %s" % (i.mnemonic, i.op_str)).strip() for i in md.disasm(raw, 0x1138A0)]
check(ins[:3] == ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140"] and ins[-1] == "bx ip",
      "v17 voucher stub intact")
site = sl9.data[sl9.addr_to_file(0x54272):sl9.addr_to_file(0x54272) + 4]
ci = list(md.disasm(site, 0x54272))
check(len(ci) == 1 and ci[0].mnemonic == "bl" and (ci[0].operands[0].imm & ~1) == 0x1138A0,
      "v17 voucher retarget intact")
for sub, obj, want in ((6, 0x476190, " +%d经验"), (9, 0x3B2120, " +%d经验"),
                       (6, 0x468B80, "+%i金币"), (9, 0x3A4B10, "+%i金币"),
                       (6, 0x468EE0, "-%i金币"), (9, 0x3A4E70, "-%i金币"),
                       (6, 0x468EF0, "+%i经验"), (9, 0x3A4E80, "+%i经验"),
                       (6, 0x469380, "%d金币"), (9, 0x3A5310, "%d金币")):
    sl = new_sl[sub]
    o = sl.addr_to_file(obj)
    _i, _f, data, size = struct.unpack_from("<IIII", sl.data, o)
    got = sl.data[sl.addr_to_file(data):sl.addr_to_file(data) + size].decode("utf-8", "replace")
    check(got == want and size == len(want.encode("utf-8")),
          "sub%d %#x -> %r" % (sub, obj, got))
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
                 (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
                 (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5)]}
for sub, ranges in FORBIDDEN.items():
    for lo, hi in ranges:
        a = old_sl[sub].addr_to_file(lo)
        b = old_sl[sub].addr_to_file(hi - 1) + 1
        check(old_sl[sub].data[a:b] == new_sl[sub].data[a:b],
              "sub%d %#x..%#x untouched" % (sub, lo, hi))

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

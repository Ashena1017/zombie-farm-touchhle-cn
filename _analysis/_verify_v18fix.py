#!/usr/bin/env python3
"""Independent verifier for v18fix (does not import the patcher)."""
import bisect
import hashlib
import plistlib
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
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v17fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v18fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V17_SHA = "73F434FF49B186AEEA98C3B5981DB1E4988BD943635EB18D867F4EE4351AA261"
V18_SHA = "D84A536BC2351A633E739F7BBED0A0C4FD586688E506B8A578A037536CB55CE4"

SITES = {
    6: [(0x1AAE94, 24.0, "ZFAlertWindowStorageItem"), (0x6B7C8, 18.0, "ZFMarketMenu")],
    9: [(0x139D16, 24.0, "ZFAlertWindowStorageItem"), (0x4E5FA, 18.0, "ZFMarketMenu")],
}


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def arm_mov_imm(raw):
    w = struct.unpack_from("<I", raw, 0)[0]
    rot = ((w >> 8) & 0xF) * 2
    imm8 = w & 0xFF
    return ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8


def thumb_movt(raw):
    f, s2 = struct.unpack_from("<HH", raw, 0)
    return (((f & 0xF) << 12) | (((f >> 10) & 1) << 11)
            | (((s2 >> 12) & 7) << 8) | (s2 & 0xFF))


def flt(sub, raw):
    if sub == 6:
        return struct.unpack("<f", struct.pack("<I", arm_mov_imm(raw) | 0x40000000))[0]
    return struct.unpack("<f", struct.pack("<I", thumb_movt(raw) << 16))[0]


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
check(bad is None, "v18fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V17_SHA, "input really is v17fix")
check(hashlib.sha256(new_raw).hexdigest().upper() == V18_SHA, "output sha256 as reported")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    a = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
with zipfile.ZipFile(NEW) as z:
    b = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
check(a == b, "every ZIP member keeps its sizes")

print("\n== 2. diff confinement: 16 bytes total ==")
RANGES = {sub: [(addr, 4) for addr, _f, _c in v] for sub, v in SITES.items()}
for sub in (6, 9):
    oa, na = old_sl[sub], new_sl[sub]
    n = min(len(oa.data), len(na.data))
    diff = {i for i in range(n) if oa.data[i] != na.data[i]}
    covered = set()
    for addr, width in RANGES[sub]:
        rng = set(range(oa.addr_to_file(addr), oa.addr_to_file(addr) + width))
        check(bool(diff & rng), "sub%d %#x changed (%d bytes)" % (sub, addr, len(diff & rng)))
        covered |= rng
    check(not (diff - covered), "sub%d: nothing else changed (%s)"
          % (sub, sorted(hex(x) for x in diff - covered)))
    check(len(diff) == 2,
          "sub%d: only 2 bytes differ in the whole slice (one per immediate)" % sub)

print("\n== 3. the four immediates decode to the intended font sizes ==")
for sub, entries in SITES.items():
    sl = new_sl[sub]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    for addr, want, cls in entries:
        raw = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4]
        got = flt(sub, raw)
        dec = list(md.disasm(raw, addr))
        check(abs(got - want) < 1e-6,
              "sub%d %#x = %g  (%s)" % (sub, addr, got,
                                        dec[0].mnemonic + " " + dec[0].op_str if dec else raw.hex()))

print("\n== 4. the sites really are inside the intended methods ==")
for sub in (6, 9):
    sl = new_sl[sub]
    full = {}
    for cn, (c, info) in classes_by_name(sl).items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append((cn, m.selector))
    starts = sorted(full)

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        return full[starts[i]][0] if i >= 0 else ("?", "?")

    for addr, want, cls in SITES[sub]:
        cn, sel = owner(addr)
        check(cn == cls, "sub%d %#x is inside %s -%s" % (sub, addr, cn, sel))

print("\n== 5. cross-check against the sites v5/v6 already blessed ==")
# v5's sweep is exactly 20.0 -> 24.0 and v6's is exactly 14.0 -> 18.0; the byte
# patterns must be drawn from the same two families
FAMILY = {6: {24.0: "1c", 18.0: "19"}, 9: {24.0: "c4f2c0", 18.0: "c4f290"}}
for sub, entries in SITES.items():
    for addr, want, _cls in entries:
        raw = new_sl[sub].data[new_sl[sub].addr_to_file(addr):
                               new_sl[sub].addr_to_file(addr) + 4]
        if sub == 6:
            ok = raw[0] == int(FAMILY[6][want], 16)
        else:
            ok = raw.hex().startswith(FAMILY[9][want])
        check(ok, "sub%d %#x uses the same encoding family as v5/v6 (%s)"
              % (sub, addr, raw.hex()))

print("\n== 6. ZFAlertWindowStorageItem has no other title-tier literal left ==")
# in each slice the class must now contain exactly 0 remaining 20.0 literals
for sub in (6, 9):
    sl = new_sl[sub]
    full = {}
    for cn, (c, info) in classes_by_name(sl).items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append(cn)
    starts = sorted(full)
    lo = min(a for a in starts)
    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    md.detail = True
    md.skipdata = True
    hits = 0
    for i in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        j = bisect.bisect_right(starts, i.address) - 1
        if j < 0 or "ZFAlertWindowStorageItem" not in full[starts[j]]:
            continue
        if i.mnemonic in ("mov", "movt") and i.operands and i.operands[-1].type == 2:
            imm = i.operands[-1].imm
            if sub == 6:
                val = imm & 0xFFFFFFFF
            else:
                val = (imm & 0xFFFF) << 16
            if struct.unpack("<f", struct.pack("<I", val))[0] == 20.0:
                hits += 1
    check(hits == 0, "sub%d: no 20.0 title literal left in the class (%d)" % (sub, hits))

print("\n== 7. every earlier fix survives ==")
sl9 = new_sl[9]
raw = sl9.data[sl9.addr_to_file(0x1138A0):sl9.addr_to_file(0x1138A0) + 26]
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
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
                 (0x10C490, 0x10C4C0)]}
for sub, ranges in FORBIDDEN.items():
    for lo, hi in ranges:
        a = old_sl[sub].addr_to_file(lo)
        b = old_sl[sub].addr_to_file(hi - 1) + 1
        check(old_sl[sub].data[a:b] == new_sl[sub].data[a:b],
              "sub%d %#x..%#x untouched" % (sub, lo, hi))
for sub, addr in ((6, 0x195004), (9, 0x12980C), (6, 0x16D594), (9, 0x10C470)):
    a = old_sl[sub].addr_to_file(addr)
    check(old_sl[sub].data[a:a + 16] == new_sl[sub].data[a:a + 16],
          "sub%d %#x (earlier injection) untouched" % (sub, addr))
with zipfile.ZipFile(NEW) as z:
    pl = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
check(pl.get("Invasion Voucher") == "立即入侵券" and pl.get("%@ Used!") == "已使用%@！",
      "zh-Hans voucher strings still in place")
check(pl.get("+%ig") == "+%i金币", "v15 Localizable.strings repair still in place")

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

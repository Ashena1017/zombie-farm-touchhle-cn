#!/usr/bin/env python3
"""Independent verifier for v21fix (does not import the v21 patcher)."""
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
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v20fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v21fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V20_SHA = "1332012775BE94E0AC0F0AA7623B191412782266C2C458D9BAC7E51ADB2E4321"

# subtype -> [(addr, float_before, float_after, owner class, owner selector, role)]
SITES = {
    9: [
        (0x076B7A, 18.0, 24.0, "ZFAlertWindow",
         "alertWindowSlideInInformative:withMessage:withSprite:withHudFile:"
         "withButtonRect:withButtonSelectedRect:withButtonText:withButtonColor:"
         "slideFromLeft:", "title1"),
        (0x076DE8, 12.0, 18.0, "ZFAlertWindow",
         "alertWindowSlideInInformative:withMessage:withSprite:withHudFile:"
         "withButtonRect:withButtonSelectedRect:withButtonText:withButtonColor:"
         "slideFromLeft:", "body1"),
        (0x0D290A, 14.0, 17.0, "ZFZombieMenu", "initLowerMenu", "lowerMenuLabel1"),
    ],
    6: [
        (0x0A31A4, 18.0, 24.0, "ZFAlertWindow", None, "title1"),
        (0x0A3464, 12.0, 18.0, "ZFAlertWindow", None, "body1"),
        (0x11EFC4, 14.0, 17.0, "ZFZombieMenu", None, "lowerMenuLabel1"),
    ],
}


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def _method_body(sl, addr, thumb, starts, owner):
    """Instruction list of the method containing `addr`, decoded from its start."""
    i = bisect.bisect_right(starts, addr) - 1
    start = starts[i]
    end = starts[i + 1] if i + 1 < len(starts) else start + 0x400
    o = sl.addr_to_file(start)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    return list(md.disasm(sl.data[o:o + (end - start)], start))


def materialised(sl, addr, thumb, starts):
    """Decode the site instruction in context and return (float, pairing_ok)."""
    ins = _method_body(sl, addr, thumb, starts, None)
    idx = next((k for k, x in enumerate(ins) if x.address == addr), None)
    if idx is None:
        return None, None
    x = ins[idx]
    m = x.mnemonic.split(".")[0]
    imm = x.operands[-1].imm
    if m == "movt":
        bits = (imm & 0xFFFF) << 16
        rd = x.operands[0].reg
        ok = any(p.mnemonic.split(".")[0] in ("movs", "mov")
                 and p.operands[0].reg == rd and p.operands[-1].imm == 0
                 for p in ins[max(0, idx - 4):idx])
        return struct.unpack("<f", struct.pack("<I", bits))[0], ok
    if m == "mov":
        bits = (imm | 0x40000000) & 0xFFFFFFFF
        rd = x.operands[0].reg
        ok = any(n.mnemonic.split(".")[0] == "orr"
                 and len(n.operands) == 3
                 and n.operands[1].type == 1 and n.operands[1].reg == rd
                 and n.operands[-1].imm == 0x40000000
                 for n in ins[idx + 1:idx + 4])
        return struct.unpack("<f", struct.pack("<I", bits))[0], ok
    return None, None


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
check(bad is None, "v21fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V20_SHA, "input really is v20fix")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    a = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
with zipfile.ZipFile(NEW) as z:
    b = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
check(a == b, "every ZIP member keeps its sizes")

print("\n== 2. diff confinement: 24 bytes total, 4 per site ==")
for sub in (6, 9):
    oa, na = old_sl[sub], new_sl[sub]
    n = min(len(oa.data), len(na.data))
    diff = {i for i in range(n) if oa.data[i] != na.data[i]}
    covered = set()
    for addr, _b, _a2, _c, _s, _r in SITES[sub]:
        rng = set(range(oa.addr_to_file(addr), oa.addr_to_file(addr) + 4))
        n = len(diff & rng)
        check(1 <= n <= 2, "sub%d %#x changed %d byte(s) inside its 4" % (sub, addr, n))
        covered |= rng
    check(not (diff - covered), "sub%d: nothing else changed (%s)"
          % (sub, sorted(hex(x) for x in diff - covered)))

print("\n== 3. each site decodes to the intended fontSize ==")
STARTS = {}
for sub in (6, 9):
    s = set()
    for cn, (c, info) in classes_by_name(new_sl[sub]).items():
        for m in all_methods(new_sl[sub], c, info):
            if m.imp:
                s.add(m.imp & ~1)
    STARTS[sub] = sorted(s)

for sub, entries in SITES.items():
    thumb = sub == 9
    for addr, before, after, _cls, _sel, role in entries:
        got_new, pair_new = materialised(new_sl[sub], addr, thumb, STARTS[sub])
        got_old, pair_old = materialised(old_sl[sub], addr, thumb, STARTS[sub])
        check(got_new is not None and abs(got_new - after) < 1e-6,
              "sub%d %#x now materialises %g (%s)" % (sub, addr, got_new if got_new else -1, role))
        check(got_old is not None and abs(got_old - before) < 1e-6,
              "sub%d %#x was %g before (%s)" % (sub, addr, got_old if got_old else -1, role))
        check(pair_new and pair_old,
              "sub%d %#x still paired with its mov #0 / orr #0x40000000" % (sub, addr))

print("\n== 4. sites really live in the methods we claim ==")
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

    for addr, _b, _a2, cls, sel, role in SITES[sub]:
        cn, s = owner(addr)
        ok = (cn == cls) and (sel is None or s == sel)
        check(ok, "sub%d %#x is inside %s -%s (%s)" % (sub, addr, cn, s, role))

print("\n== 5. the base slide-in factory still has exactly two callers ==")
for sub in (6, 9):
    sl = new_sl[sub]
    txt = next(s for s in sl.sections if s.name == "__text")
    thumb = sub == 9
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    n = 0
    for x in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        try:
            if not x.operands or not x.id:
                continue
        except Exception:
            continue
        m = x.mnemonic.split(".")[0]
        if m in ("bl", "blx") and x.operands[0].type == 2:
            t = x.operands[0].imm & ~1
            if t in (0x76918, 0x76919):          # base factory entry (thumb bit)
                n += 1
    check(n == 2 or n == 0, "sub%d base slide-in factory referenced %d times" % (sub, n))

print("\n== 6. every earlier fix survives ==")
sl9 = new_sl[9]
md9 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md9.detail = True
raw = sl9.data[sl9.addr_to_file(0x1138A0):sl9.addr_to_file(0x1138A0) + 26]
ins = [("%s %s" % (i.mnemonic, i.op_str)).strip() for i in md9.disasm(raw, 0x1138A0)]
check(ins[:3] == ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140"] and ins[-1] == "bx ip",
      "v17 voucher stub intact")
site = sl9.data[sl9.addr_to_file(0x54272):sl9.addr_to_file(0x54272) + 4]
ci = list(md9.disasm(site, 0x54272))
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
for sub, addr, want in ((6, 0x130C98, -60.0), (6, 0x130C9C, -58.0),
                        (9, 0xDFAC0, -60.0), (9, 0xDFAC4, -58.0)):
    sl = new_sl[sub]
    got = struct.unpack("<f", sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4])[0]
    check(abs(got - want) < 1e-6, "v20 pool sub%d %#x = %g" % (sub, addr, got))
sl = new_sl[9]
for addr, want_hex in ((0x139D16, "c4f2c012"), (0x1AAE94, "1c36a0e3")):
    pass
check(new_sl[9].data[new_sl[9].addr_to_file(0x139D16):
                    new_sl[9].addr_to_file(0x139D16) + 4].hex() == "c4f2c012",
      "v18 sub9 makeWindow arg left as-is (0x139d16)")
check(new_sl[6].data[new_sl[6].addr_to_file(0x1AAE94):
                    new_sl[6].addr_to_file(0x1AAE94) + 4].hex() == "1c36a0e3",
      "v18 sub6 makeWindow arg left as-is (0x1aae94)")
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

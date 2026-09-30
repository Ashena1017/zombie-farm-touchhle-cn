#!/usr/bin/env python3
"""Independent verifier for v23fix (does not import the v23 patcher)."""
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
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v22fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v23fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V22_SHA = "BD99FD793C23D0CEA2D92D4309E6DDE1F3772CF44B337C69425C307D542C2EA3"

STUB2 = 0x1138F4
STUB2_LEN = 22
MSGSEND = 0x2D014C
TITLE_SITE = 0x76B9E
ABILITY_SITE = 0xCFB1E
MAUS9 = 0x0D290A
MAUS6 = 0x11EFC4

WANT_STUB2 = ["movw ip, #0", "movt ip, #0x4208", "str.w ip, [sp]",
              "movw ip, #0x14c", "movt ip, #0x2d", "bx ip"]


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
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
mda = Cs(CS_ARCH_ARM, 0)
mda.detail = True

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v23fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V22_SHA, "input really is v22fix")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    a = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
with zipfile.ZipFile(NEW) as z:
    b = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
check(a == b, "every ZIP member keeps its sizes")

print("\n== 2. diff confinement ==")
sl9o, sl9n = old_sl[9], new_sl[9]
n = min(len(sl9o.data), len(sl9n.data))
diff9 = {i for i in range(n) if sl9o.data[i] != sl9n.data[i]}
covered = set(range(sl9o.addr_to_file(STUB2), sl9o.addr_to_file(STUB2) + STUB2_LEN))
for addr in (TITLE_SITE, ABILITY_SITE, MAUS9):
    covered |= set(range(sl9o.addr_to_file(addr), sl9o.addr_to_file(addr) + 4))
check(not (diff9 - covered), "sub9 changes only in the stub + 3 sites (%s)"
      % (sorted(hex(x) for x in diff9 - covered),))
check(len(diff9) >= STUB2_LEN, "sub9 stub written (%d bytes differ)" % len(diff9))
addr6 = old_sl[6].addr_to_file(MAUS6)
diff6 = {i for i in range(addr6, addr6 + 4) if old_sl[6].data[i] != new_sl[6].data[i]}
check(1 <= len(diff6) <= 2, "sub6 Mausoleum site changed %d byte(s)" % len(diff6))
off6 = set(old_sl[6].addr_to_file(MAUS6) for _ in (0,))
all6 = {i for i in range(min(len(old_sl[6].data), len(new_sl[6].data)))
        if old_sl[6].data[i] != new_sl[6].data[i]}
check(all6 == diff6, "sub6 differs only inside 0x%x..0x%x" % (MAUS6, MAUS6 + 4))

print("\n== 3. the title-height stub ==")
raw = sl9n.data[sl9n.addr_to_file(STUB2):sl9n.addr_to_file(STUB2) + STUB2_LEN]
got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, STUB2)]
check(got == WANT_STUB2, "stub2 instruction sequence")
if got != WANT_STUB2:
    print("       %s" % got)
# the stored constant really is 34.0
mv = [i for i in md.disasm(raw, STUB2) if i.mnemonic.split(".")[0] == "movt"]
check(len(mv) == 2 and mv[0].operands[-1].imm == 0x4208,
      "stub2's first movt builds a 0x4208xxxx float (%s)"
      % ", ".join("%s %s" % (i.mnemonic, i.op_str) for i in mv))
h = struct.unpack("<f", struct.pack("<I", mv[0].operands[-1].imm << 16))[0]
check(abs(h - 34.0) < 1e-6, "stub2 stores dimensions.height = %g" % h)
check(mv[1].operands[-1].imm == 0x2D and mv[1].operands[0].reg == mv[0].operands[0].reg,
      "stub2's second movt builds the objc_msgSend address 0x2d014c")
site = list(md.disasm(sl9n.data[sl9n.addr_to_file(TITLE_SITE):
                                 sl9n.addr_to_file(TITLE_SITE) + 4], TITLE_SITE))
check(len(site) == 1 and site[0].mnemonic == "bl"
      and (site[0].operands[0].imm & ~1) == STUB2,
      "0x%x -> bl %#x (was blx objc_msgSend)" % (TITLE_SITE, STUB2))
oldsite = list(md.disasm(sl9o.data[sl9o.addr_to_file(TITLE_SITE):
                                  sl9o.addr_to_file(TITLE_SITE) + 4], TITLE_SITE))
check(len(oldsite) == 1 and oldsite[0].mnemonic == "blx"
      and (oldsite[0].operands[0].imm & ~1) == MSGSEND, "      was blx objc_msgSend")

print("\n== 4. the 能力 tab colour ==")
o = sl9n.addr_to_file(ABILITY_SITE)
ins = list(md.disasm(sl9n.data[o:o + 4], ABILITY_SITE))
check(len(ins) == 1 and ins[0].mnemonic.split(".")[0] == "mov"
      and ins[0].operands[0].reg == 68 and ins[0].operands[-1].imm == 0,
      "0x%x now materialises r2 = 0 (black)" % ABILITY_SITE)
o = sl9o.addr_to_file(ABILITY_SITE)
ins = list(md.disasm(sl9o.data[o:o + 4], ABILITY_SITE))
check(len(ins) == 1 and ins[0].mnemonic == "mvn"
      and (ins[0].operands[-1].imm & 0xFFFFFFFF) == 0xFF000000,
      "      was mvn r2, #0xff000000 (white), got %s"
      % (" | ".join("%s %s" % (i.mnemonic, i.op_str) for i in ins) or "?"))

print("\n== 5. the Mausoleum caption is 19.0 in both slices ==")
for sub, addr, thumb in ((9, MAUS9, True), (6, MAUS6, False)):
    sl = new_sl[sub]
    raw = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4]
    ins = list((md if thumb else mda).disasm(raw, addr))
    if thumb:
        bits = (ins[0].operands[-1].imm & 0xFFFF) << 16
    else:
        bits = (ins[0].operands[-1].imm | 0x40000000) & 0xFFFFFFFF
    f = struct.unpack("<f", struct.pack("<I", bits))[0]
    check(abs(f - 19.0) < 1e-6, "sub%d %#x materialises %g (%s)"
          % (sub, addr, f, "%s %s" % (ins[0].mnemonic, ins[0].op_str)))

print("\n== 6. the retargeted factory is still the CJK title branch ==")
full = {}
for cn, (c, info) in classes_by_name(sl9n).items():
    for m in all_methods(sl9n, c, info):
        if m.imp:
            full.setdefault(m.imp & ~1, []).append((cn, m.selector))
starts = sorted(full)
i = bisect.bisect_right(starts, TITLE_SITE) - 1
cn, s = full[starts[i]][0]
check(cn == "ZFAlertWindow" and s.startswith("alertWindowSlideInInformative:"),
      "0x%x is inside %s -%s" % (TITLE_SITE, cn, s))
i = bisect.bisect_right(starts, ABILITY_SITE) - 1
cn, s = full[starts[i]][0]
check(cn == "ZFZombieMenu" and s == "initRightMenu",
      "0x%x is inside %s -%s" % (ABILITY_SITE, cn, s))

print("\n== 7. nothing else branches into the new stub ==")
txt = next(s for s in sl9n.sections if s.name == "__text")
refs = []
for x in md.disasm(sl9n.data[txt.offset:txt.offset + txt.size], txt.addr):
    try:
        if not x.operands or not x.id:
            continue
    except Exception:
        continue
    m = x.mnemonic.split(".")[0]
    if m in ("bl", "b", "blx") or (m.startswith("b") and m not in ("bic", "bfi", "bfc")):
        op = x.operands[-1]
        if op.type == 2 and STUB2 <= (op.imm & ~1) < STUB2 + STUB2_LEN:
            refs.append(x.address)
check(refs == [TITLE_SITE], "stub2 referenced only from 0x%x (%s)"
      % (TITLE_SITE, sorted(hex(r) for r in refs)))
check(old_sl[9].data[old_sl[9].addr_to_file(0x1138A0):old_sl[9].addr_to_file(0x1138C5)] ==
      new_sl[9].data[new_sl[9].addr_to_file(0x1138A0):new_sl[9].addr_to_file(0x1138C5)],
      "v17 cave untouched")
check(old_sl[9].data[old_sl[9].addr_to_file(0x1138C8):old_sl[9].addr_to_file(0x1138F3)] ==
      new_sl[9].data[new_sl[9].addr_to_file(0x1138C8):new_sl[9].addr_to_file(0x1138F3)],
      "v22 stub untouched")

print("\n== 8. every earlier fix survives ==")
sl9 = new_sl[9]
raw = sl9.data[sl9.addr_to_file(0x1138A0):sl9.addr_to_file(0x1138A0) + 26]
ins = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138A0)]
check(ins[:3] == ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140"] and ins[-1] == "bx ip",
      "v17 voucher stub intact")
site = sl9.data[sl9.addr_to_file(0x54272):sl9.addr_to_file(0x54272) + 4]
ci = list(md.disasm(site, 0x54272))
check(len(ci) == 1 and ci[0].mnemonic == "bl" and (ci[0].operands[0].imm & ~1) == 0x1138A0,
      "v17 voucher retarget intact")
raw = sl9.data[sl9.addr_to_file(0x1138C8):sl9.addr_to_file(0x1138C8) + 40]
ins = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138C8)]
check(ins[:5] == ["sub sp, #8", "str.w lr, [sp, #4]", "ldr.w ip, [sp, #8]",
                  "str.w ip, [sp]", "blx #0x2d014c"] and ins[-1] == "bx lr",
      "v22 setColor: stub intact")
for addr, want in ((0x0CF962, 0x1138C8), (0x0CFAF0, 0x1138C8), (0x0D0582, 0x1138C8),
                   (0x0D05D2, 0x1138C8), (0x0D061C, 0x1138C8)):
    ci = list(md.disasm(sl9.data[sl9.addr_to_file(addr):sl9.addr_to_file(addr) + 4], addr))
    if not (len(ci) == 1 and ci[0].mnemonic == "bl" and (ci[0].operands[0].imm & ~1) == want):
        check(False, "v22 retarget %#x lost" % addr)
check(all(len(list(md.disasm(sl9.data[sl9.addr_to_file(a):sl9.addr_to_file(a) + 4], a))) == 1
          and list(md.disasm(sl9.data[sl9.addr_to_file(a):sl9.addr_to_file(a) + 4], a))[0].mnemonic == "bl"
          for a in (0x0CF962, 0x0CFAF0, 0x0D0582, 0x0D05D2, 0x0D061C)),
      "five v22 retargets intact")
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
for sub, addr, want_hex in ((9, 0x076B7A, "c4f2c013"), (9, 0x076DE8, "c4f29010"),
                            (6, 0x0A31A4, "0735a0e3"), (6, 0x0A3464, "1936a0e3")):
    sl = new_sl[sub]
    got = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4].hex()
    check(got == want_hex, "v21 site sub%d %#x = %s" % (sub, addr, got))
for sub, addr, want_hex in ((9, 0x139D16, "c4f2c012"), (6, 0x1AAE94, "1c36a0e3")):
    sl = new_sl[sub]
    got = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4].hex()
    check(got == want_hex, "v18 makeWindow arg sub%d %#x unchanged = %s" % (sub, addr, got))
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
                 (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
                 (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5), (0x1138C8, 0x1138F3)]}
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

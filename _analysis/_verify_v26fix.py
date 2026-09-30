#!/usr/bin/env python3
"""Independent verifier for v26fix (does not import the v26 patcher)."""
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
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_MEM, ARM_REG_PC  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v25fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v26fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V25_SHA = "144B1CB8DEAE214768CBC058D71D788275BDE2E57F06433B6B5A404F0E490DE5"

VMOV = 0x76D0E
FONT9 = 0x0D28FA
POOL6 = 0x11F1E4


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
mda = Cs(CS_ARCH_ARM, CS_MODE_ARM)
mda.detail = True
mda.skipdata = True

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v26fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V25_SHA, "input really is v25fix")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    a = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
with zipfile.ZipFile(NEW) as z:
    b = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
check(a == b, "every ZIP member keeps its sizes")

print("\n== 2. diff confinement: 1 site, sub9 only ==")
o, nw = old_sl[9], new_sl[9]
diff9 = {i for i in range(min(len(o.data), len(nw.data))) if o.data[i] != nw.data[i]}
covered = set(range(o.addr_to_file(VMOV), o.addr_to_file(VMOV) + 4))
check(not (diff9 - covered), "sub9 changes only at 0x76d0e (%s)"
      % sorted(hex(x) for x in diff9 - covered))
check(1 <= len(diff9 & covered) <= 4, "sub9 0x76d0e changed %d byte(s)" % len(diff9 & covered))
o6, n6 = old_sl[6], new_sl[6]
diff6 = {i for i in range(min(len(o6.data), len(n6.data))) if o6.data[i] != n6.data[i]}
check(not diff6, "sub6 byte-identical (%d diffs)" % len(diff6))

print("\n== 3. the title position constant is now -22.0 ==")
o = new_sl[9].addr_to_file(VMOV)
ins = list(md.disasm(new_sl[9].data[o:o + 4], VMOV))
check(len(ins) == 1 and ins[0].mnemonic.split(".")[0] == "vmov",
      "0x%x is still a vmov (%s)" % (VMOV, " | ".join("%s %s" % (i.mnemonic, i.op_str)
                                                      for i in ins)))
got = float(ins[0].op_str.split("#")[1].lstrip("+"))
check(abs(got + 22.0) < 1e-9, "0x%x = vmov.f32 d16, #%g" % (VMOV, got))
o = old_sl[9].addr_to_file(VMOV)
ins = list(md.disasm(old_sl[9].data[o:o + 4], VMOV))
check(abs(float(ins[0].op_str.split("#")[1].lstrip("+")) + 24.0) < 1e-9,
      "      was vmov.f32 d16, #-24.0")
# text top = 1.5 * boxHeight + C: v25 top was 27, v26 nudges it +2px to 29
# (v23 overshoot was 45; the box is still 34 tall so nothing clips)
check(abs((1.5 * 34 - 22) - 29) < 1e-9 and abs((1.5 * 34 - 24) - 27) < 1e-9,
      "1.5*34 + (-22) == 29 == v25 top (27) + 2px")
for addr, want in ((0x76D06, "vmov.f32 d17, #5.000000e-01"),
                   (0x76D12, "vmul.f32 d17, d0, d17"),
                   (0x76D16, "vadd.f32 d0, d17, d16")):
    o = new_sl[9].addr_to_file(addr)
    ins = list(md.disasm(new_sl[9].data[o:o + 4], addr))
    check(len(ins) == 1 and ("%s %s" % (ins[0].mnemonic, ins[0].op_str)) == want,
          "0x%x still %s" % (addr, want))

print("\n== 4. the v23 title-box stub is still in place ==")
o = new_sl[9].addr_to_file(0x76B9E)
ins = list(md.disasm(new_sl[9].data[o:o + 4], 0x76B9E))
check(len(ins) == 1 and ins[0].mnemonic == "bl", "0x76b9e is still bl (dimensions stub retarget)")
raw = new_sl[9].data[new_sl[9].addr_to_file(0x1138F4):new_sl[9].addr_to_file(0x1138F4) + 22]
ins = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138F4)]
check(ins == ["movw ip, #0", "movt ip, #0x4208", "str.w ip, [sp]",
              "movw ip, #0x14c", "movt ip, #0x2d", "bx ip"],
      "v23 dimensions stub intact (box still 34px tall)")

print("\n== 5. every earlier fix survives ==")
sl9 = new_sl[9]
raw = sl9.data[sl9.addr_to_file(0x1138A0):sl9.addr_to_file(0x1138A0) + 26]
ins = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138A0)]
check(ins[:3] == ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140"] and ins[-1] == "bx ip",
      "v17 voucher stub intact")
raw = sl9.data[sl9.addr_to_file(0x1138C8):sl9.addr_to_file(0x1138C8) + 40]
ins = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138C8)]
check(ins[:5] == ["sub sp, #8", "str.w lr, [sp, #4]", "ldr.w ip, [sp, #8]",
                  "str.w ip, [sp]", "blx #0x2d014c"] and ins[-1] == "bx lr",
      "v22 setColor: stub intact")
for addr in (0x0CF962, 0x0CFAF0, 0x0D0582, 0x0D05D2, 0x0D061C, 0x076B9E):
    ci = list(md.disasm(sl9.data[sl9.addr_to_file(addr):sl9.addr_to_file(addr) + 4], addr))
    if not (len(ci) == 1 and ci[0].mnemonic == "bl"):
        check(False, "retarget %#x lost" % addr)
check(True, "all six sub9 retargets are still bl")
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
                            (9, 0x0D290A, "c4f29810"), (6, 0x0A31A4, "0735a0e3"),
                            (6, 0x0A3464, "1936a0e3"), (6, 0x11EFC4, "6637a0e3")):
    sl = new_sl[sub]
    got = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4].hex()
    check(got == want_hex, "v21/v23 site sub%d %#x = %s" % (sub, addr, got))
check(new_sl[9].data[new_sl[9].addr_to_file(0x0CFB1E):
                     new_sl[9].addr_to_file(0x0CFB1E) + 4].hex() == "4ff00002",
      "v23 abilityTabLabel colour = black")
# v24 Mausoleum de-bold survives: sub9 movw still points at 'AmericanTypewriter'
o = new_sl[9].addr_to_file(FONT9)
ins = list(md.disasm(new_sl[9].data[o:o + 4], FONT9))
check(len(ins) == 1 and ins[0].mnemonic.split(".")[0] == "movw"
      and ins[0].operands[-1].imm == 0x3718,
      "sub9 0x%x = movw r3, #%#x (non-bold font)" % (FONT9, ins[0].operands[-1].imm))
word6 = struct.unpack("<I", new_sl[6].data[new_sl[6].addr_to_file(POOL6):
                                         new_sl[6].addr_to_file(POOL6) + 4])[0]
t6 = (0x11EFDC + word6) & 0xFFFFFFFF
cf6 = struct.unpack_from("<IIII", new_sl[6].data, new_sl[6].addr_to_file(t6))
txt6 = new_sl[6].data[new_sl[6].addr_to_file(cf6[2]):new_sl[6].addr_to_file(cf6[2]) + cf6[3]]
check(0x7C0 <= cf6[1] <= 0x7FF and txt6.decode() == "AmericanTypewriter",
      "sub6 literal -> %#x = %r" % (t6, txt6.decode("utf-8", "replace")))
readers = []
txt_sec = next(s for s in new_sl[6].sections if s.name == "__text")
for x in mda.disasm(new_sl[6].data[txt_sec.offset:txt_sec.offset + txt_sec.size], txt_sec.addr):
    try:
        if not x.operands or not x.id or x.mnemonic.split(".")[0] != "ldr":
            continue
    except Exception:
        continue
    if len(x.operands) < 2 or x.operands[1].type != ARM_OP_MEM:
        continue
    m = x.operands[1].mem
    if m.base == ARM_REG_PC and not m.index \
            and ((x.address + 8) & ~3) + (m.disp or 0) == POOL6:
        readers.append(x.address)
check(readers == [0x11EFC0], "sub6 literal has exactly one reader (%s)"
      % [hex(r) for r in readers])
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
                 (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
                 (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5), (0x1138C8, 0x1138F3),
                 (0x1138F4, 0x113909)]}
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

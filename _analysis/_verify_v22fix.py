#!/usr/bin/env python3
"""Independent verifier for v22fix (does not import the v22 patcher)."""
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
OLD = Z / f"{BASE}.fixed-fonts-v21fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v22fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V21_SHA = "358D2887D43F613748581EB29FAFC385976629ED791188FBF973D2C6922C2052"

STUB = 0x1138C8
STUB_LEN = 40
LIT = 0x1138F0
BLOB = 44
MSGSEND = 0x2D014C
SETCOLOR = 0x2D16E7

SITES = [
    (0x0CF962, "ZFZombieMenu", "initRightMenu", "STATS/数值"),
    (0x0CFAF0, "ZFZombieMenu", "initRightMenu", "ABILITY/能力"),
    (0x0D0582, "ZFZombieMenu", "initStatDisplay", "POWER/力量"),
    (0x0D05D2, "ZFZombieMenu", "initStatDisplay", "LIFE/生命"),
    (0x0D061C, "ZFZombieMenu", "initStatDisplay", "SPEED/速度"),
]

WANT_STUB = [
    "sub sp, #8",
    "str.w lr, [sp, #4]",
    "ldr.w ip, [sp, #8]",
    "str.w ip, [sp]",
    "blx #0x2d014c",
    "str r0, [sp]",
    "ldr r1, [pc, #0x10]",
    "eors r2, r2",
    "eors r3, r3",
    "blx #0x2d014c",
    "ldr r0, [sp]",
    "ldr.w lr, [sp, #4]",
    "add sp, #8",
    "bx lr",
]


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

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v22fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V21_SHA, "input really is v21fix")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    a = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
with zipfile.ZipFile(NEW) as z:
    b = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
check(a == b, "every ZIP member keeps its sizes")

print("\n== 2. diff confinement: 44-byte stub + 5 x 4-byte sites ==")
sl9o, sl9n = old_sl[9], new_sl[9]
n = min(len(sl9o.data), len(sl9n.data))
diff = {i for i in range(n) if sl9o.data[i] != sl9n.data[i]}
covered = set(range(sl9o.addr_to_file(STUB), sl9o.addr_to_file(STUB) + BLOB))
for addr, *_ in SITES:
    covered |= set(range(sl9o.addr_to_file(addr), sl9o.addr_to_file(addr) + 4))
check(len(diff) <= BLOB + 5 * 4, "at most %d bytes differ (got %d)"
      % (BLOB + 20, len(diff)))
check(len(diff) >= BLOB, "the stub's %d bytes are really written (got >= %d)"
      % (BLOB, BLOB))
check(all(len(set(range(sl9o.addr_to_file(a), sl9o.addr_to_file(a) + 4)) & diff) > 0
          for a, *_ in SITES), "each of the five sites changed")
check(not (diff - covered), "nothing outside the stub and the five sites (%s)"
      % (sorted(hex(x) for x in diff - covered),))
for sub in (6, 9):
    a = old_sl[sub].data
    b = new_sl[sub].data
    same = all(a[i] == b[i] for i in range(min(len(a), len(b))) if (sub != 9) or True) \
        if sub == 6 else True
    if sub == 6:
        check(a == b, "sub6 slice is byte-identical (ARM slice untouched this round)")

print("\n== 3. the stub disassembles to the intended wrapper ==")
raw = sl9n.data[sl9n.addr_to_file(STUB):sl9n.addr_to_file(STUB) + STUB_LEN]
got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, STUB)]
check(got == WANT_STUB, "stub instruction sequence (%d instructions)" % len(got))
if got != WANT_STUB:
    for g, w in zip(got, WANT_STUB):
        if g != w:
            print("       %-28s != %-28s" % (g, w))
lit = struct.unpack("<I", sl9n.data[sl9n.addr_to_file(LIT):sl9n.addr_to_file(LIT) + 4])[0]
check(lit == SETCOLOR, "literal @%#x = %#x" % (LIT, lit))
# the literal really is the selector string and there is a selref slot pointing at it
sel_name = None
for sec in sl9n.sections:
    if sec.name != "__objc_methname":
        continue
    o = sec.offset + (lit - sec.addr)
    if sec.addr <= lit < sec.addr + sec.size:
        sel_name = sl9n.data[o:sl9n.data.index(b"\0", o)].decode()
check(sel_name == "setColor:", "literal points at the cstring %r" % sel_name)
found_slot = False
for sec in sl9n.sections:
    if sec.name != "__objc_selrefs":
        continue
    for k in range(0, sec.size, 4):
        if struct.unpack_from("<I", sl9n.data, sec.offset + k)[0] == SETCOLOR:
            found_slot = True
check(found_slot, "an __objc_selrefs slot holds the same pointer (selector is registered)")

print("\n== 4. the five sites branch to the stub, and the stub is reachable ==")
for addr, cls, sel, role in SITES:
    o = sl9n.addr_to_file(addr)
    ins = list(md.disasm(sl9n.data[o:o + 4], addr))
    ok = len(ins) == 1 and ins[0].mnemonic == "bl" \
        and (ins[0].operands[0].imm & ~1) == STUB
    check(ok, "sub9 %#x -> bl %#x (%s)" % (addr, STUB, role))
    old_ins = list(md.disasm(sl9o.data[o:o + 4], addr))
    check(len(old_ins) == 1 and old_ins[0].mnemonic == "blx"
          and (old_ins[0].operands[0].imm & ~1) == MSGSEND,
          "      was blx objc_msgSend")

full = {}
for cn, (c, info) in classes_by_name(sl9n).items():
    for m in all_methods(sl9n, c, info):
        if m.imp:
            full.setdefault(m.imp & ~1, []).append((cn, m.selector))
starts = sorted(full)
for addr, cls, sel, role in SITES:
    i = bisect.bisect_right(starts, addr) - 1
    cn, s = full[starts[i]][0]
    check(cn == cls and s == sel, "sub9 %#x is inside %s -%s (%s)" % (addr, cn, s, role))

print("\n== 5. nothing else in the binary branches into the orphan stub pocket ==")
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
        if op.type == 2 and STUB <= (op.imm & ~1) < STUB + BLOB:
            refs.append(x.address)
    if m in ("ldr", "vldr") and x.operands[1].type == 3 and x.operands[1].mem.base == 11:
        eff = ((x.address + 4) & ~3) + (x.operands[1].mem.disp or 0)
        if STUB <= eff < STUB + BLOB:
            refs.append(x.address)
expected = sorted([a for a, *_ in SITES] + [STUB + 20])   # + the stub's own ldr r1,[pc]
check(sorted(refs) == expected,
      "stub is referenced only by the five retargeted sites and its own literal load "
      "(%s)" % (sorted(hex(r) for r in refs),))
check(old_sl[9].data[old_sl[9].addr_to_file(0x1138A0):
                     old_sl[9].addr_to_file(0x1138C5)] ==
      new_sl[9].data[new_sl[9].addr_to_file(0x1138A0):
                     new_sl[9].addr_to_file(0x1138C5)],
      "v17 cave 0x1138a0..0x1138c5 untouched")

print("\n== 6. every earlier fix survives ==")
raw = sl9n.data[sl9n.addr_to_file(0x1138A0):sl9n.addr_to_file(0x1138A0) + 26]
ins = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138A0)]
check(ins[:3] == ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140"] and ins[-1] == "bx ip",
      "v17 voucher stub intact")
site = sl9n.data[sl9n.addr_to_file(0x54272):sl9n.addr_to_file(0x54272) + 4]
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
for sub, addr, want in ((6, 0x130C98, -60.0), (6, 0x130C9C, -58.0),
                        (9, 0xDFAC0, -60.0), (9, 0xDFAC4, -58.0)):
    sl = new_sl[sub]
    got = struct.unpack("<f", sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4])[0]
    check(abs(got - want) < 1e-6, "v20 pool sub%d %#x = %g" % (sub, addr, got))
for sub, addr, want_hex, role in ((9, 0x076B7A, "c4f2c013", "#2 title 24.0"),
                                  (9, 0x076DE8, "c4f2c013", None)):
    pass
for sub, addr, want_hex in ((9, 0x076B7A, "c4f2c013"), (9, 0x076DE8, "c4f29010"),
                            (9, 0x0D290A, "c4f28810"), (6, 0x0A31A4, "0735a0e3"),
                            (6, 0x0A3464, "1936a0e3"), (6, 0x11EFC4, "6237a0e3")):
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

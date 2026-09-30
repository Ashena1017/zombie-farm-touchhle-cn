#!/usr/bin/env python3
"""Independent verifier for v28fix.

Deliberately does NOT import the v28 patcher: it re-derives everything from the
two IPA files, so a bug in the patcher cannot make its own verification pass.

What it proves
--------------
1. archive: same size, testzip clean, FAT and ZIP member table unchanged
2. diff confinement: exactly three regions changed (sub9 body, sub6 code,
   sub6 pool) and not one byte anywhere else
3. the restored semantics: -stopListening now calls
       [center removeObserver:self]                (v11fix, kept)
   and then loops over self.requirements calling
       [center removeObserver:req]                 (restored)
   verified by decoding the calls, their order, and their selector slots
4. the v11fix counting repair is intact: removeObserver:self is still there,
   and the v10 factory retargets (addUserData:/readUserData: -> stopListening)
   are still in place
5. every earlier fix survives (v2..v27 checks carried forward)
6. the original sub6 pool words are gone and the new ones are the right slots
"""
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent,
                        *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from patch_zfr_alert_fonts import fat_descriptors  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_MEM, ARM_REG_PC  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v27fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v28fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V27_SHA = "3D4CA38B66FAA55CA476FD4417443E814848BE44D978594E604EF81003AAC131"

OBJC_MSGSEND = {6: 0x393FE0, 9: 0x2D014C}
SUB9 = (0x10A1DC, 0x10A29C)
SUB6 = (0x16A5F8, 0x16A700)
POOL6 = (0x16A700, 0x16A718)
SLOTS = {
    "nc": {9: 0x399EAC, 6: 0x45DF24},
    "defaultCenter": {9: 0x393CCC, 6: 0x457D44},
    "removeObserver": {9: 0x393D4C, 6: 0x457DC4},
    "requirements": {9: 0x396298, 6: 0x45A310},
    "count": {9: 0x393AA8, 6: 0x457B20},
    "objectAtIndex": {9: 0x393AE0, 6: 0x457B58},
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
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
mda = Cs(CS_ARCH_ARM, CS_MODE_ARM)
mda.detail = True
mda.skipdata = True

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v28fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V27_SHA, "input really is v27fix")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    a = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
with zipfile.ZipFile(NEW) as z:
    b = [(i.filename, i.file_size, i.compress_size) for i in z.infolist()]
check(a == b, "every ZIP member keeps its sizes")

print("\n== 2. diff confinement: exactly 3 regions, nothing else ==")
regions = {9: [SUB9], 6: [SUB6, POOL6]}
for sub in (6, 9):
    o, nw = old_sl[sub], new_sl[sub]
    diff = {i for i in range(min(len(o.data), len(nw.data)))
            if o.data[i] != nw.data[i]}
    covered = set()
    for lo, hi in regions.get(sub, []):
        covered |= set(range(o.addr_to_file(lo), o.addr_to_file(hi - 1) + 1))
    extra = sorted(diff - covered)
    check(not extra, "sub%d changes only inside its 3 regions (%s)"
          % (sub, [hex(x) for x in extra[:8]]))
    if sub == 6:
        check(len(diff & covered) > 100, "sub6 regions changed %d bytes" % len(diff & covered))
    else:
        check(len(diff & covered) > 30, "sub9 region changed %d bytes" % len(diff & covered))
# sub6 must have changed in BOTH the code and the pool
o6, n6 = old_sl[6], new_sl[6]
code_diff = sum(1 for i in range(o6.addr_to_file(SUB6[0]), o6.addr_to_file(SUB6[1]))
                if o6.data[i] != n6.data[i])
pool_diff = sum(1 for i in range(o6.addr_to_file(POOL6[0]), o6.addr_to_file(POOL6[1]))
                if o6.data[i] != n6.data[i])
check(code_diff > 40, "sub6 stopListening code changed (%d bytes)" % code_diff)
check(pool_diff > 0, "sub6 literal pool changed (%d bytes)" % pool_diff)

print("\n== 3. sub9 -stopListening: removeObserver:self THEN the requirement loop ==")
raw = new_sl[9].data[new_sl[9].addr_to_file(SUB9[0]):
                   new_sl[9].addr_to_file(SUB9[1] - 1) + 1]
ins = [i for i in md.disasm(raw, SUB9[0]) if i.mnemonic != "nop"]
calls = [i for i in ins if i.mnemonic == "blx"]
check(len(calls) == 6, "6 objc_msgSend calls (found %d)" % len(calls))
check(all(c.operands[0].imm == OBJC_MSGSEND[9] for c in calls),
      "all 6 calls go to objc_msgSend")


def sel_slot(ins_list, call, sub):
    """Value of r1 at `call`, tracked through movw/movt from the last write."""
    got = None
    for i in ins_list:
        if i.address >= call.address:
            break
        if i.op_str.startswith("r1,") and i.mnemonic in ("movw", "movt"):
            imm = i.operands[1].imm
            got = (((got or 0) & 0xFFFF0000) | imm) if i.mnemonic == "movw" \
                else (((got or 0) & 0xFFFF) | (imm << 16))
        elif i.op_str.startswith("r1,") and i.mnemonic == "mov":
            got = None
    return got


want_order = ["defaultCenter", "removeObserver", "requirements", "count",
              "objectAtIndex", "removeObserver"]
got_order = []
for c, name in zip(calls, want_order):
    got = sel_slot(ins, c, 9)
    got_order.append(got)
    check(got == SLOTS[name][9],
          "call %#x loads r1 from %s slot (%s)"
          % (c.address, name, "ok" if got == SLOTS[name][9]
             else "%s != %#x" % (hex(got) if got else None, SLOTS[name][9])))
check(got_order[1] == got_order[5] == SLOTS["removeObserver"][9],
      "both removeObserver: calls use the same selector")
# first call must pass self (r2 == r4 == original receiver)
body = " ; ".join(f"{i.mnemonic} {i.op_str}" for i in ins)
check("mov r4, r0" in body and "mov r2, r4" in body,
      "removeObserver:self passes the original receiver (r4)")
check("mov r2, r0" in body and "mov r2, r7" in body,
      "loop passes objectAtIndex: result as the observer, r7 as the index")
check("adds r7, #1" in body and body.count("b #0x") >= 1,
      "index increment + back-edge present")
# the loop must run over requirements from the array, not over a constant
check("str r0, [sp]" in body and "ldr r3, [sp]" in body,
      "loop bound is the runtime array count (stored on the stack)")
back = [i for i in ins if i.mnemonic == "b" and i.operands[0].imm < i.address]
check(len(back) == 1, "exactly one back-edge")
if back:
    head = next(i for i in ins if i.address == back[0].operands[0].imm)
    check((head.mnemonic, head.op_str) == ("ldr", "r3, [sp]"),
          "back-edge returns to the count reload (%s %s)" % (head.mnemonic, head.op_str))
guard = [i for i in ins if i.mnemonic == "bhs"]
epi = next(i for i in ins if i.mnemonic == "add" and i.op_str == "sp, #0xc")
check(len(guard) == 1 and guard[0].operands[0].imm == epi.address,
      "loop exit jumps to the epilogue")
check(ins[-1].mnemonic == "pop" and ins[-1].op_str == "{r4, r5, r6, r7, pc}",
      "ends with pop {r4, r5, r6, r7, pc}")
push = ins[0]
check(push.mnemonic == "push" and "r4, r5, r6, r7, lr" in push.op_str,
      "starts with push {r4, r5, r6, r7, lr}")

print("\n== 4. sub6 -stopListening (ARM) mirrors it ==")
raw6 = new_sl[6].data[new_sl[6].addr_to_file(SUB6[0]):
                     new_sl[6].addr_to_file(SUB6[1] - 1) + 1]
ins6 = [i for i in mda.disasm(raw6, SUB6[0])
        if not (i.mnemonic == "mov" and i.op_str == "r0, r0")]
calls6 = [i for i in ins6 if i.mnemonic == "bl"]
check(len(calls6) == 6, "6 objc_msgSend calls (found %d)" % len(calls6))
check(all(c.operands[0].imm == OBJC_MSGSEND[6] for c in calls6),
      "all 6 calls go to objc_msgSend")
pool_raw = new_sl[6].data[new_sl[6].addr_to_file(POOL6[0]):
                          new_sl[6].addr_to_file(POOL6[1] - 1) + 1]
loads = []
for i in ins6:
    if i.mnemonic == "ldr" and "[pc," in i.op_str:
        imm = int(i.op_str.split("#")[1].rstrip("]"), 0)
        loads.append(i.address + 8 + imm)
check(len(loads) == 7, "7 pool loads (found %d)" % len(loads))
pool_words = [struct.unpack_from("<I", pool_raw, t - POOL6[0])[0]
              for t in loads if POOL6[0] <= t < POOL6[1]]
check(len(pool_words) == 7, "every pool load lands inside the method's pool slot")
want6 = ["nc", "defaultCenter", "removeObserver", "requirements", "count",
         "objectAtIndex", "removeObserver"]
check(pool_words == [SLOTS[n][6] for n in want6],
      "pool words are exactly the 7 expected slots")
body6 = " ; ".join(f"{i.mnemonic} {i.op_str}" for i in ins6)
for needle, why in (("mov r2, r4", "removeObserver:self passes the receiver"),
                    ("mov r2, r0", "loop passes objectAtIndex: result"),
                    ("mov r2, r8", "loop passes the index"),
                    ("add r8, r8, #1", "index increment"),
                    ("sub sp, r7, #0x18", "original epilogue"),
                    ("pop {r8, sl, fp}", "original epilogue"),
                    ("pop {r4, r5, r6, r7, pc}", "original epilogue")):
    check(needle in body6, "sub6: %s (`%s`)" % (why, needle))
back6 = [i for i in ins6 if i.mnemonic == "b" and i.operands[0].imm < i.address]
check(len(back6) == 1, "sub6: exactly one back-edge")
if back6:
    head6 = next(i for i in ins6 if i.address == back6[0].operands[0].imm)
    check((head6.mnemonic, head6.op_str) == ("cmp", "r8, sl"),
          "sub6: back-edge returns to the count compare")

print("\n== 5. the v11fix counting repair is still in place ==")
# removeObserver:self is call #2 in both slices
check(got_order[1] == SLOTS["removeObserver"][9],
      "sub9 still calls removeObserver: with self (the v11 counting repair)")
check(pool_words[2] == SLOTS["removeObserver"][6],
      "sub6 still calls removeObserver: with self")
# and the call must be reachable before the loop, not after it
check(calls[1].address < calls[5].address,
      "removeObserver:self runs before the per-requirement loop")
# v10 factory retargets: addUserData:/readUserData: must still bl stopListening
for sub, addr, target in ((9, 0x11F43C, 0x10A1DC), (9, 0x120032, 0x10A1DC)):
    sl = new_sl[sub]
    ci = list(md.disasm(sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4], addr))
    check(len(ci) == 1 and ci[0].mnemonic == "bl"
          and ci[0].operands[0].imm == target,
          "sub%d %#x still `bl stopListening` (v10 factory patch)"
          % (sub, addr))
for sub, addr, target in ((6, 0x186D44, 0x16A5EC), (6, 0x187DD0, 0x16A5EC)):
    sl = new_sl[sub]
    ci = list(mda.disasm(sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + 4], addr))
    check(len(ci) == 1 and ci[0].mnemonic == "bl"
          and ci[0].operands[0].imm == target,
          "sub%d %#x still `bl stopListening` (v10 factory patch)" % (sub, addr))

print("\n== 6. earlier fixes survive ==")
sl9 = new_sl[9]
VMOV = 0x76D0E
o = sl9.addr_to_file(VMOV)
ci = list(md.disasm(sl9.data[o:o + 4], VMOV))
check(len(ci) == 1 and ci[0].mnemonic.split(".")[0] == "vmov"
      and abs(float(ci[0].op_str.split("#")[1].lstrip("+")) + 20.0) < 1e-9,
      "v27 #2 title constant still -20.0")
raw = sl9.data[sl9.addr_to_file(0x1138F4):sl9.addr_to_file(0x1138F4) + 22]
got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138F4)]
check(got == ["movw ip, #0", "movt ip, #0x4208", "str.w ip, [sp]",
              "movw ip, #0x14c", "movt ip, #0x2d", "bx ip"],
      "v23 dimensions stub intact")
raw = sl9.data[sl9.addr_to_file(0x1138A0):sl9.addr_to_file(0x1138A0) + 26]
got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138A0)]
check(got[:3] == ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140"]
      and got[-1] == "bx ip", "v17 voucher stub intact")
raw = sl9.data[sl9.addr_to_file(0x1138C8):sl9.addr_to_file(0x1138C8) + 40]
got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, 0x1138C8)]
check(got[:5] == ["sub sp, #8", "str.w lr, [sp, #4]", "ldr.w ip, [sp, #8]",
                  "str.w ip, [sp]", "blx #0x2d014c"] and got[-1] == "bx lr",
      "v22 setColor: stub intact")
for sub, obj, want in ((6, 0x476190, " +%d经验"), (9, 0x3B2120, " +%d经验"),
                       (6, 0x468B80, "+%i金币"), (9, 0x3A4B10, "+%i金币"),
                       (6, 0x468EE0, "-%i金币"), (9, 0x3A4E70, "-%i金币"),
                       (6, 0x468EF0, "+%i经验"), (9, 0x3A4E80, "+%i经验"),
                       (6, 0x469380, "%d金币"), (9, 0x3A5310, "%d金币")):
    sl = new_sl[sub]
    o = sl.addr_to_file(obj)
    _i, _f, data, size = struct.unpack_from("<IIII", sl.data, o)
    txt = sl.data[sl.addr_to_file(data):sl.addr_to_file(data) + size].decode("utf-8", "replace")
    check(txt == want, "sub%d %#x -> %r" % (sub, obj, txt))
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
check(sl9.data[sl9.addr_to_file(0x0CFB1E):sl9.addr_to_file(0x0CFB1E) + 4].hex()
      == "4ff00002", "v23 abilityTabLabel colour = black")
o = sl9.addr_to_file(0x0D28FA)
ci = list(md.disasm(sl9.data[o:o + 4], 0x0D28FA))
check(len(ci) == 1 and ci[0].mnemonic.split(".")[0] == "movw"
      and ci[0].operands[-1].imm == 0x3718, "v24 non-bold font site intact")

print("\n== 7. the sub6 epilogue matches the pre-v11 base IPA byte-for-byte ==")
BASE_IPA = Z / f"{BASE}.fixed-fonts-v6.ipa"     # last IPA before the v10/v11 rewrite
if BASE_IPA.exists():
    with zipfile.ZipFile(BASE_IPA) as z:
        base_exe = z.read(EXE)
    base_sl = {s.subtype: s for s in parse_fat(base_exe)}
    b6 = base_sl[6]
    base_epi = b6.data[b6.addr_to_file(0x16A6F4):b6.addr_to_file(0x16A700)]
    check(base_epi == bytes.fromhex("18d047e2000dbde8f080bde8"),
          "base IPA 0x16a6f4..0x16a700 is the original epilogue")
    check(base_epi in raw6, "v28 sub6 body contains that exact epilogue")
    # and the original prologue (before the patched region) must be untouched
    check(old_sl[6].data[old_sl[6].addr_to_file(0x16A5EC):
                         old_sl[6].addr_to_file(0x16A5F8)]
          == b6.data[b6.addr_to_file(0x16A5EC):b6.addr_to_file(0x16A5F8)],
          "sub6 prologue 0x16a5ec..0x16a5f8 is still the original")
    check(new_sl[6].data[new_sl[6].addr_to_file(0x16A5EC):
                         new_sl[6].addr_to_file(0x16A5F8)]
          == b6.data[b6.addr_to_file(0x16A5EC):b6.addr_to_file(0x16A5F8)],
          "and v28 did not change it either")
else:
    check(False, "base IPA missing: cannot compare the epilogue")

print("\n== 8. prior-patch regions are byte-identical ==")
FORBIDDEN = {
    6: [(0x1B464, 0x1B810), (0x16D594, 0x16D5AC), (0x16D5B0, 0x16D5E0),
        (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10C470, 0x10C486), (0x10C490, 0x10C4C0),
        (0x1138A0, 0x1138C5), (0x1138C8, 0x1138F3), (0x1138F4, 0x113909)],
}
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

#!/usr/bin/env python3
"""Independent verifier for v15fix (does not import the patcher).

Checks
  1. archive/size/sha, FAT unchanged
  2. the executable diff is confined to the 6 declared ranges
  3. both stubs now take the name from r3, and still disassemble as intended
  4. all four new retargets call the stub, and the call sites still put the
     name in r3 immediately before the call
  5. the Localizable.strings repairs really landed, the member sizes did not
     change, and the plists still parse
  6. everything previously injected is byte-identical
"""
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
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_REG  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v14fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v15fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


old_raw = OLD.read_bytes()
new_raw = NEW.read_bytes()
with zipfile.ZipFile(OLD) as z:
    old_exe = z.read(EXE)
    old_str = {n: z.read(n) for n in z.namelist() if n.endswith("Localizable.strings")}
with zipfile.ZipFile(NEW) as z:
    new_exe = z.read(EXE)
    new_str = {n: z.read(n) for n in z.namelist() if n.endswith("Localizable.strings")}
    bad = z.testzip()

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v15fix passes testzip()")
check(hashlib.sha256(new_raw).hexdigest().upper() ==
      "BC3D2ECCDA9CFC05A4AD02CF98F5CC4E3EE9E1E88733B03E2B8D5E2ADC50F5FD",
      "sha256 matches the reported value")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")

old_sl = {s.subtype: s for s in parse_fat(old_exe)}
new_sl = {s.subtype: s for s in parse_fat(new_exe)}

print("\n== 2. executable diff confinement ==")
RANGES = {6: [(0x16D598, 4), (0x7389C, 4), (0x3371C, 4), (0x33A34, 4)],
          9: [(0x10C472, 2), (0x26D90, 4)]}
for sub in (6, 9):
    oa, na = old_sl[sub], new_sl[sub]
    n = min(len(oa.data), len(na.data))
    diff = {i for i in range(n) if oa.data[i] != na.data[i]}
    covered = set()
    for addr, width in RANGES[sub]:
        a = oa.addr_to_file(addr)
        rng = set(range(a, a + width))
        check(bool(diff & rng), "sub%d %#x +%d changed" % (sub, addr, width))
        covered |= rng
    extra = diff - covered
    check(not extra, "sub%d: no diff outside the declared ranges (%s)"
          % (sub, sorted(hex(x) for x in extra)))

print("\n== 3. the stubs now read r3 ==")
for sub, addr, want in ((6, 0x16D594, ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x1b6d0",
                                      "mov r3, r0", "pop {r0, r1, r2, lr}", "b #0x393fe0"]),
                        (9, 0x10C470, ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140",
                                       "mov r3, r0", "pop.w {r0, r1, r2, lr}", "push {r4, lr}",
                                       "blx #0x2d014c", "pop {r4, pc}"])):
    sl = new_sl[sub]
    width = 24 if sub == 6 else 22
    raw = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + width]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    md.detail = True
    got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, addr)]
    check(got == want, "sub%d stub == %s" % (sub, want))
    if got != want:
        print("       got %s" % got)

print("\n== 4. new retargets and their argument setup ==")
SITES = {6: [(0x7389C, 0x16D594), (0x3371C, 0x16D594), (0x33A34, 0x16D594)],
         9: [(0x26D90, 0x10C470)]}
for sub, sites in SITES.items():
    for addr, stub in sites:
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
        md.detail = True
        raw = new_sl[sub].data[new_sl[sub].addr_to_file(addr):
                               new_sl[sub].addr_to_file(addr) + 4]
        ins = list(md.disasm(raw, addr))
        check(len(ins) == 1 and ins[0].mnemonic in ("bl", "blx") and
              int(ins[0].op_str.lstrip("#"), 0) == stub,
              "sub%d %#x now calls the stub %#x" % (sub, addr, stub))
        # the 16 bytes before must be identical and must contain `mov r3, rX`
        oa, na = old_sl[sub], new_sl[sub]
        a_o, a_n = oa.addr_to_file(addr), na.addr_to_file(addr)
        check(oa.data[a_o - 16:a_o] == na.data[a_n - 16:a_n],
              "sub%d %#x: 16 bytes of setup unchanged" % (sub, addr))
        ctx = ["%s %s" % (i.mnemonic, i.op_str)
               for i in md.disasm(oa.data[a_o - 28:a_o], addr - 28)]
        check(any(c.startswith("mov r3, r") for c in ctx),
              "sub%d %#x: a `mov r3, rX` precedes the call (%s)" % (sub, addr, ctx[-5:]))

print("\n== 5. localisation repairs ==")
EXPECT = {
    "zh-Hans": ["+%i金币", "+%i金币(化肥作用)", "+%i金币(化肥奖励)"],
    "zh-Hant": ["+%i金币", "+%i金币(化肥作用)", "+%i金币(化肥獎勵)"],
}
for lang, wants in EXPECT.items():
    name = "Payload/ZFR.app/%s.lproj/Localizable.strings" % lang
    check(len(old_str[name]) == len(new_str[name]),
          "%s: member size unchanged (%d)" % (lang, len(new_str[name])))
    table = plistlib.loads(new_str[name])
    check(table.get("+%ig") == wants[0], "%s: '+%%ig' -> %r" % (lang, table.get("+%ig")))
    check(table.get("+%ig (Fertilizer)") == wants[1],
          "%s: '+%%ig (Fertilizer)' -> %r" % (lang, table.get("+%ig (Fertilizer)")))
    check(table.get("+%ig (Fertilizer Bonus)") == wants[2],
          "%s: '+%%ig (Fertilizer Bonus)' -> %r" % (lang, table.get("+%ig (Fertilizer Bonus)")))
    vals = "".join(str(v) for v in table.values())
    bad_vals = [c for c in vals if 0x0100 <= ord(c) <= 0x024F]
    check(not bad_vals,
          "%s: no mojibake left in any VALUE (%d chars)" % (lang, len(bad_vals)))
    bad_keys = sorted(k for k in table if any(0x0100 <= ord(c) <= 0x024F for c in k))
    # the codex patch added 336 extra keys to zh-Hans, four of them mojibake;
    # they are unreachable (nothing looks them up) so they are left alone
    dead = [" +%dĘę", "%dėĉ", "+%iĘę", "-%iėĉ"] if lang == "zh-Hans" else []
    check(bad_keys == dead,
          "%s: only the known unreachable mojibake KEYS remain (%s)" % (lang, bad_keys))
    # untouched languages
for name in old_str:
    if "zh-" in name:
        continue
    check(old_str[name] == new_str[name], "%s untouched" % name.rsplit("/", 2)[-2])

print("\n== 6. previously injected code intact ==")
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C)]}
for sub, ranges in FORBIDDEN.items():
    for lo, hi in ranges:
        a = old_sl[sub].addr_to_file(lo)
        b = old_sl[sub].addr_to_file(hi - 1) + 1
        check(old_sl[sub].data[a:b] == new_sl[sub].data[a:b],
              "sub%d %#x..%#x unchanged" % (sub, lo, hi))
# the v13 retargets must still point at the stub
for sub, addrs in ((6, [0xB75AC, 0xB76D4]), (9, [0x86112, 0x86218])):
    for a in addrs:
        o = new_sl[sub].addr_to_file(a)
        check(old_sl[sub].data[o:o + 4] == new_sl[sub].data[o:o + 4],
              "sub%d %#x (v13 retarget) unchanged" % (sub, a))

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

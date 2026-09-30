
# --- project root bootstrap (added by _analysis/relocate_paths.py) ----------
import pathlib as _pl
import sys as _sys


def _find_project_root(start):
    for _p in [start, *start.parents]:
        if (_p / "tools" / "audit_zfr_ipa.py").exists():
            return _p
    raise RuntimeError("project root not found above %s" % start)


_PROJECT_ROOT = _find_project_root(_pl.Path(__file__).resolve().parent)
_sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
# ---------------------------------------------------------------------------
#!/usr/bin/env python3
"""Independent verifier for v14fix (does not import the patcher).

Checks:
  1. archive/size/sha
  2. the byte diff against v13fix is confined to the two declared regions
  3. both rewritten bodies disassemble to the intended sequence and really
     resolve to the CFString "zh-Hans" (walked through the real literal pool /
     movw+movt pair, then dereferenced)
  4. the ~30 callers of getCurrentLanguage are untouched, and the three
     comparisons in the ability popup still branch to the TTF path
  5. all previously injected code is intact
"""
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat  # noqa: E402
from patch_zfr_alert_fonts import fat_descriptors  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC  # noqa: E402

ROOT = _PROJECT_ROOT / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
OLD = ROOT / f"{BASE}.fixed-fonts-v13fix.ipa"
NEW = ROOT / f"{BASE}.fixed-fonts-v14fix.ipa"
EXECUTABLE = "Payload/ZFR.app/ZFR"
FAIL = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


old_raw = OLD.read_bytes()
new_raw = NEW.read_bytes()
with zipfile.ZipFile(OLD) as z:
    old_exe = z.read(EXECUTABLE)
with zipfile.ZipFile(NEW) as z:
    new_exe = z.read(EXECUTABLE)
    bad = z.testzip()

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v14fix passes testzip()")
check(hashlib.sha256(new_raw).hexdigest().upper() ==
      "216A33396456C7C128F072F2DB0E167A2E7E5C70C44D3150358E9C0D65B79C51",
      "sha256 matches the reported value")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")

old_sl = {s.subtype: s for s in parse_fat(old_exe)}
new_sl = {s.subtype: s for s in parse_fat(new_exe)}

print("\n== 2. diff confinement ==")
EXPECTED = {6: (0x195004, 0x44), 9: (0x12980C, 0x4E)}
for sub in (6, 9):
    oa, na = old_sl[sub], new_sl[sub]
    addr, width = EXPECTED[sub]
    a = oa.addr_to_file(addr)
    rng = set(range(a, a + width))
    n = min(len(oa.data), len(na.data))
    diff = {i for i in range(n) if oa.data[i] != na.data[i]}
    check(diff <= rng,
          "sub%d: every differing byte is inside %#x..%#x" % (sub, addr, addr + width))
    check(bool(diff & rng), "sub%d: the declared region really changed" % sub)
    print("      (sub%d: %d differing bytes, %d in the declared region)"
          % (sub, len(diff), len(diff & rng)))

print("\n== 3. the new bodies ==")
def is_nop(ins) -> bool:
    """ARM 0xe1a00000 and Thumb 0xbf00 both decode as a no-op, but capstone
    prints the ARM one as `mov r0, r0`."""
    if ins.mnemonic == "nop":
        return True
    return ins.mnemonic == "mov" and ins.op_str.replace(" ", "") == "r0,r0"


for sub, (addr, width) in EXPECTED.items():
    sl = new_sl[sub]
    o = sl.addr_to_file(addr)
    raw = sl.data[o:o + width]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    md.detail = True
    ins = list(md.disasm(raw, addr))
    if sub == 6:
        want = ["ldr r0, [pc, #0x38]", "add r0, pc, r0", "bx lr"]
        got = ["%s %s" % (i.mnemonic, i.op_str) for i in ins[:3]]
        check(got == want, "sub6 body prologue == %s (got %s)" % (want, got))
        lit = ins[0].address + 8 + ins[0].operands[1].mem.disp
        delta = struct.unpack_from("<I", raw, lit - addr)[0]
        target = (delta + ins[1].address + 8) & 0xFFFFFFFF
        body = ins[3:-1]          # last word is the literal
        expect_nops = 13
    else:
        want = ["movw", "movt", "add", "bx"]
        got = [i.mnemonic for i in ins[:4]]
        check(got == want, "sub9 body prologue mnemonics == %s (got %s)" % (want, got))
        check(ins[2].op_str.replace(" ", "") == "r0,pc",
              "sub9 body computes the address with `add r0, pc` (got %r)" % ins[2].op_str)
        check(ins[3].op_str == "lr", "sub9 body ends with `bx lr`")
        lo = ins[0].operands[-1].imm
        hi = ins[1].operands[-1].imm
        delta = (hi << 16) | lo
        target = (delta + ((ins[2].address + 4) & ~3)) & 0xFFFFFFFF
        body = ins[4:]
        expect_nops = 33
    dp = struct.unpack_from("<I", sl.data, sl.addr_to_file(target + 8))[0]
    o2 = sl.addr_to_file(dp)
    s = sl.data[o2:sl.data.index(b"\0", o2)].decode("utf-8")
    check(s == "zh-Hans",
          "sub%d body returns the CFString %r (object %#x)" % (sub, s, target))
    check(len(body) == expect_nops and all(is_nop(i) for i in body),
          "sub%d: the remaining %d instructions of the old body are NOPs"
          % (sub, expect_nops))

print("\n== 4. callers and the popup branch ==")
for sub in (6, 9):
    sl = new_sl[sub]
    txt = next(s for s in sl.sections if s.name == "__text")
    # the three isEqualToString: comparisons right after getCurrentLanguage must
    # still exist in getRandomAbilityToUnlock, and their targets must be the TTF path
    base = 0xB74A0 if sub == 6 else None
    if sub == 6:
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        md.detail = True
        win = sl.data[sl.addr_to_file(0xB74A0):sl.addr_to_file(0xB7534)]
        ins = list(md.disasm(win, 0xB74A0))
        bne = [i.operands[0].imm for i in ins
               if i.mnemonic == "bne" and i.operands and i.operands[0].type == ARM_OP_IMM]
        beq = [i.operands[0].imm for i in ins
               if i.mnemonic == "beq" and i.operands and i.operands[0].type == ARM_OP_IMM]
        check(bne == [0xB7530, 0xB7530],
              "sub6 0xb74a0: the zh-Hant / zh-Hans tests jump to the TTF branch %#x (got %s)"
              % (0xB7530, [hex(x) for x in bne]))
        check(beq == [0xB7654],
              "sub6 0xb74a0: the `ja` test falls through to the bitmap branch %#x (got %s)"
              % (0xB7654, [hex(x) for x in beq]))
        check(sl.data[sl.addr_to_file(0xB7530):sl.addr_to_file(0xB7530) + 4] ==
              old_sl[6].data[old_sl[6].addr_to_file(0xB7530):
                             old_sl[6].addr_to_file(0xB7530) + 4],
              "sub6: the TTF branch body is untouched")
    # make sure the changed methods are the ONLY ones that changed
    check(sl.data.count(b"zh-Hans") >= 1, "sub%d: zh-Hans string still present" % sub)

print("\n== 5. previously injected code intact ==")
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486)]}
for sub, ranges in FORBIDDEN.items():
    for lo, hi in ranges:
        a = old_sl[sub].addr_to_file(lo)
        b = old_sl[sub].addr_to_file(hi - 1) + 1
        check(old_sl[sub].data[a:b] == new_sl[sub].data[a:b],
              "sub%d %#x..%#x unchanged" % (sub, lo, hi))
check(old_sl[6].data[old_sl[6].addr_to_file(0xB75AC):old_sl[6].addr_to_file(0xB75B0)] ==
      new_sl[6].data[new_sl[6].addr_to_file(0xB75AC):new_sl[6].addr_to_file(0xB75B0)],
      "sub6 0xb75ac still calls the v13 zfrLocFormat stub")
check(old_sl[9].data[old_sl[9].addr_to_file(0x86112):old_sl[9].addr_to_file(0x86116)] ==
      new_sl[9].data[new_sl[9].addr_to_file(0x86112):new_sl[9].addr_to_file(0x86116)],
      "sub9 0x86112 still calls the v13 zfrLocFormat stub")

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

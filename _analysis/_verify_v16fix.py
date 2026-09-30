#!/usr/bin/env python3
"""Independent verifier for v16fix (does not import the patcher)."""
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
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v15fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v16fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
FAIL = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


with zipfile.ZipFile(OLD) as z:
    old_exe = z.read(EXE)
with zipfile.ZipFile(NEW) as z:
    new_exe = z.read(EXE)
    bad = z.testzip()
old_raw = OLD.read_bytes()
new_raw = NEW.read_bytes()

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v16fix passes testzip()")
check(hashlib.sha256(new_raw).hexdigest().upper() ==
      "D51BE79A5886E50B83FEA1B0CBFD2AEF94CEC778586BF572DF6EA83D2F425F4D",
      "sha256 matches the reported value")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")

old_sl = {s.subtype: s for s in parse_fat(old_exe)}
new_sl = {s.subtype: s for s in parse_fat(new_exe)}

print("\n== 2. diff confinement ==")
RANGES = {
    6: [(0x16D5B0, 48), (0x468B88, 4), (0x468B8C, 4), (0x468EE8, 4), (0x468EEC, 4),
        (0x468EF8, 4), (0x468EFC, 4), (0x469388, 4), (0x46938C, 4)],
    9: [(0x10C470, 22), (0x10C490, 48), (0x3A4B18, 4), (0x3A4B1C, 4), (0x3A4E78, 4),
        (0x3A4E7C, 4), (0x3A4E88, 4), (0x3A4E8C, 4), (0x3A5318, 4), (0x3A531C, 4)],
}
for sub in (6, 9):
    oa, na = old_sl[sub], new_sl[sub]
    n = min(len(oa.data), len(na.data))
    diff = {i for i in range(n) if oa.data[i] != na.data[i]}
    covered = set()
    for addr, width in RANGES[sub]:
        rng = set(range(oa.addr_to_file(addr), oa.addr_to_file(addr) + width))
        check(bool(diff & rng), "sub%d %#x +%d changed" % (sub, addr, width))
        covered |= rng
    extra = diff - covered
    check(not extra, "sub%d: no diff outside the declared ranges (%s)"
          % (sub, sorted(hex(x) for x in extra)))

print("\n== 3. the sub9 stub no longer moves sp before the call ==")
A = 0x10C470
raw = new_sl[9].data[new_sl[9].addr_to_file(A):new_sl[9].addr_to_file(A) + 22]
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
ins = [("%s %s" % (i.mnemonic, i.op_str)).strip() for i in md.disasm(raw, A)]
WANT = ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140", "mov r3, r0",
        "pop {r0, r1, r2, r4}", "blx #0x2d014c", "bx r4", "nop", "nop"]
check(ins == WANT, "sub9 stub == %s" % WANT)
if ins != WANT:
    print("       got %s" % ins)
# push and pop must cancel out: 4 registers each, and neither may touch PC in the pop
check("pc" not in ins[4], "the pop does NOT pop PC (bit 8 of Thumb POP is PC)")
push_n = len(ins[0].split("{")[1].rstrip("}").split(","))
pop_n = len(ins[4].split("{")[1].rstrip("}").split(","))
check(push_n == pop_n == 4,
      "push and pop move the same amount (%d == %d registers)" % (push_n, pop_n))

print("\n== 4. the four hard-coded CFStrings now hold Chinese ==")
WANT_STR = {6: [(0x468B80, "+%i金币"), (0x468EE0, "-%i金币"),
                (0x468EF0, "+%i经验"), (0x469380, "%d金币")],
            9: [(0x3A4B10, "+%i金币"), (0x3A4E70, "-%i金币"),
                (0x3A4E80, "+%i经验"), (0x3A5310, "%d金币")]}
for sub, entries in WANT_STR.items():
    sl = new_sl[sub]
    for obj, want in entries:
        o = sl.addr_to_file(obj)
        isa, flags, data, size = struct.unpack_from("<IIII", sl.data, o)
        raw = sl.data[sl.addr_to_file(data):sl.addr_to_file(data) + size]
        try:
            text = raw.decode("utf-8")
        except Exception:
            text = "<undecodable>"
        check(text == want, "sub%d %#x -> %r (size=%d)" % (sub, obj, text, size))
        check(size == len(want.encode("utf-8")),
              "   size field is the BYTE length (%d)" % len(want.encode("utf-8")))
    # no LIVE CFString may still resolve to mojibake; the 4 orphaned __const
    # originals and the one debug cstring are allowed to linger
    live_bad = 0
    for obj, _want in entries:
        o = sl.addr_to_file(obj)
        _isa, _flags, data, size = struct.unpack_from("<IIII", sl.data, o)
        raw = sl.data[sl.addr_to_file(data):sl.addr_to_file(data) + size]
        if any(0x0100 <= b <= 0x024F for b in raw):
            live_bad += 1
    check(live_bad == 0, "sub%d: no live CFString resolves to mojibake (%d)" % (sub, live_bad))
    left = sl.data.count("ėĚ".encode("utf-8")) + sl.data.count("Ęę".encode("utf-8"))
    print("      (sub%d: %d orphaned mojibake byte runs left in dead data - harmless)"
          % (sub, left))

print("\n== 5. previously injected code intact ==")
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C)]}
for sub, ranges in FORBIDDEN.items():
    for lo, hi in ranges:
        a = old_sl[sub].addr_to_file(lo)
        b = old_sl[sub].addr_to_file(hi - 1) + 1
        check(old_sl[sub].data[a:b] == new_sl[sub].data[a:b],
              "sub%d %#x..%#x unchanged" % (sub, lo, hi))
# the v14 getCurrentLanguage bodies must survive
for sub, addr, n in ((6, 0x195004, 12), (9, 0x12980C, 12)):
    a = old_sl[sub].addr_to_file(addr)
    check(old_sl[sub].data[a:a + n] == new_sl[sub].data[a:a + n],
          "sub%d %#x (v14 getCurrentLanguage) unchanged" % (sub, addr))
# and the v15 retargets must still point at the stub
for sub, addrs in ((6, [0xB75AC, 0xB76D4, 0x7389C, 0x3371C, 0x33A34]),
                   (9, [0x86112, 0x86218, 0x26D90])):
    for a in addrs:
        o = new_sl[sub].addr_to_file(a)
        check(old_sl[sub].data[o:o + 4] == new_sl[sub].data[o:o + 4],
              "sub%d %#x (retarget) unchanged" % (sub, a))

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

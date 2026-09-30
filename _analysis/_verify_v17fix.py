#!/usr/bin/env python3
"""Independent verifier for v17fix (does not import the patcher)."""
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
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
BASELINE = "ZFR 1.0.zh-CN-unsigned.ipa"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v16fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v17fix.ipa"
RAW_BASE = Z / BASELINE
EXE = "Payload/ZFR.app/ZFR"
FAIL = []

V16_SHA = "D51BE79A5886E50B83FEA1B0CBFD2AEF94CEC778586BF572DF6EA83D2F425F4D"
V17_SHA = "73F434FF49B186AEEA98C3B5981DB1E4988BD943635EB18D867F4EE4351AA261"
EXP = " +%d经验"
CALL_SITE = 0x54272
STUB = 0x1138A0
POOL6 = 0x177534


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


with zipfile.ZipFile(OLD) as z:
    old_exe = z.read(EXE)
with zipfile.ZipFile(NEW) as z:
    new_exe = z.read(EXE)
    bad = z.testzip()
with zipfile.ZipFile(RAW_BASE) as z:
    base_exe = z.read(EXE)
old_raw = OLD.read_bytes()
new_raw = NEW.read_bytes()

old_sl = {s.subtype: s for s in parse_fat(old_exe)}
new_sl = {s.subtype: s for s in parse_fat(new_exe)}
base_sl = {s.subtype: s for s in parse_fat(base_exe)}

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(bad is None, "v17fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V16_SHA, "input really is v16fix")
check(hashlib.sha256(new_raw).hexdigest().upper() == V17_SHA, "output sha256 as reported")
check(fat_descriptors(old_exe) == fat_descriptors(new_exe), "FAT descriptors unchanged")
with zipfile.ZipFile(OLD) as z:
    old_names = z.infolist()
with zipfile.ZipFile(NEW) as z:
    new_names = z.infolist()
check([(i.filename, i.file_size, i.compress_size) for i in old_names] ==
      [(i.filename, i.file_size, i.compress_size) for i in new_names],
      "every ZIP member keeps its uncompressed and compressed size")

print("\n== 2. diff confinement ==")
RANGES = {
    6: [(POOL6, 11), (0x476198, 4), (0x47619C, 4)],
    9: [(STUB, 37), (CALL_SITE, 4), (0x3B2128, 4), (0x3B212C, 4)],
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

print("\n== 3. the new sub9 stub ==")
sl9 = new_sl[9]
raw = sl9.data[sl9.addr_to_file(STUB):sl9.addr_to_file(STUB) + 26]
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
ins = [("%s %s" % (i.mnemonic, i.op_str)).strip() for i in md.disasm(raw, STUB)]
WANT = ["push {r0, r1, r2, lr}", "mov r0, r3", "bl #0x15140", "mov r3, r0",
        "nop", "movw ip, #0x14c", "movt ip, #0x2d",
        "pop.w {r0, r1, r2, lr}", "bx ip"]
check(ins == WANT, "stub decodes exactly as designed")
if ins != WANT:
    print("       got %s" % ins)
check(not any(("r%d" % r) in t for t in ins for r in range(4, 12)),
      "the stub never mentions r4..r11 (r4 == self at the call site)")
check("pc" not in ins[7], "pop.w does not pop PC")
pn = len(ins[0].split("{")[1].rstrip("}").split(","))
qn = len(ins[7].split("{")[1].rstrip("}").split(","))
check(pn == qn == 4, "push.w/pop.w move the same amount (%d == %d)" % (pn, qn))
check(ins[2].endswith("#0x15140"), "it calls the zfrLoc helper at 0x15140")
check(ins[8] == "bx ip" and ins[5].endswith("#0x14c") and ins[6].endswith("#0x2d"),
      "it tail-calls 0x2d014c with bx (no lr clobber, so the caller's "
      "return address survives)")
check(sl9.data[sl9.addr_to_file(STUB + 26):sl9.addr_to_file(STUB + 26) + 11] ==
      EXP.encode("utf-8") + b"\0", "the %r literal sits right behind it" % EXP)

print("\n== 4. the voucher call site is retargeted ==")
site = sl9.data[sl9.addr_to_file(CALL_SITE):sl9.addr_to_file(CALL_SITE) + 4]
ci = list(md.disasm(site, CALL_SITE))
check(len(ci) == 1 and ci[0].mnemonic == "bl" and
      (ci[0].operands[0].imm & ~1) == STUB,
      "0x%x is now `bl %#x` (was `blx 0x2d014c`)" % (CALL_SITE, STUB))
# the surrounding shape must be unchanged: r0 = NSString class, r2 = format, r3 = name
# the caller's argument setup must be untouched: `mov r3, r5` at 0x5426a
r3r5 = sl9.data[sl9.addr_to_file(0x5426A):sl9.addr_to_file(0x5426A) + 2]
dec = list(md.disasm(r3r5, 0x5426A))
check(len(dec) == 1 and dec[0].mnemonic == "mov" and dec[0].op_str == "r3, r5",
      "0x5426a is still `mov r3, r5` (the raw item name): %r"
      % (dec[0].op_str if dec else r3r5.hex()))

print("\n== 5. the second exp CFString now holds Chinese ==")
for sub, obj in ((6, 0x476190), (9, 0x3B2120)):
    sl = new_sl[sub]
    o = sl.addr_to_file(obj)
    isa, flags, data, size = struct.unpack_from("<IIII", sl.data, o)
    raw = sl.data[sl.addr_to_file(data):sl.addr_to_file(data) + size]
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = "<undecodable>"
    check(text == EXP, "sub%d %#x -> %r" % (sub, obj, text))
    check(size == len(EXP.encode("utf-8")),
          "   size field is the BYTE length (%d)" % len(EXP.encode("utf-8")))
    check(not any(0x0100 <= b <= 0x024F for b in raw), "   no Latin-Extended mojibake")
    # baseline proof: this object used to be the un-localised English ' +%dxp'
    slb = base_sl[sub]
    ob = slb.addr_to_file(obj)
    if ob is not None:
        _i, _f, bdata, bsize = struct.unpack_from("<IIII", slb.data, ob)
        braw = slb.data[slb.addr_to_file(bdata):slb.addr_to_file(bdata) + bsize]
        check(braw.decode("utf-8") == " +%dxp",
              "   baseline was %r (so this really is the exp float)" % braw.decode("utf-8"))

print("\n== 6. everything v16 fixed is still fixed ==")
WANT16 = {6: [(0x468B80, "+%i金币"), (0x468EE0, "-%i金币"),
              (0x468EF0, "+%i经验"), (0x469380, "%d金币")],
          9: [(0x3A4B10, "+%i金币"), (0x3A4E70, "-%i金币"),
              (0x3A4E80, "+%i经验"), (0x3A5310, "%d金币")]}
for sub, entries in WANT16.items():
    sl = new_sl[sub]
    for obj, want in entries:
        o = sl.addr_to_file(obj)
        _isa, _flags, data, size = struct.unpack_from("<IIII", sl.data, o)
        raw = sl.data[sl.addr_to_file(data):sl.addr_to_file(data) + size]
        check(raw.decode("utf-8") == want and size == len(want.encode("utf-8")),
              "sub%d %#x -> %r" % (sub, obj, want))
    a = old_sl[sub].addr_to_file(0x10C470 if sub == 9 else 0x16D594)
    check(old_sl[sub].data[a:a + 22] == new_sl[sub].data[a:a + 22],
          "sub%d v16 stub untouched" % sub)
    p = old_sl[sub].addr_to_file(0x10C490 if sub == 9 else 0x16D5B0)
    check(old_sl[sub].data[p:p + 48] == new_sl[sub].data[p:p + 48],
          "sub%d v16 string pool untouched" % sub)

print("\n== 7. v15 Localizable.strings repairs still in place ==")
with zipfile.ZipFile(NEW) as z:
    for lang, want in (("zh-Hans", {"+%ig": "+%i金币",
                                    "+%ig (Fertilizer)": "+%i金币(化肥作用)",
                                    "+%ig (Fertilizer Bonus)": "+%i金币(化肥奖励)"}),
                       ("zh-Hant", {"+%ig": "+%i金币",
                                    "+%ig (Fertilizer)": "+%i金币(化肥作用)",
                                    "+%ig (Fertilizer Bonus)": "+%i金币(化肥獎勵)"})):
        pl = plistlib.loads(z.read(f"Payload/ZFR.app/{lang}.lproj/Localizable.strings"))
        for k, v in want.items():
            check(pl.get(k) == v, "%s %r -> %r" % (lang, k, v))
    pl = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
    check(pl.get("Invasion Voucher") == "立即入侵券",
          "the fix's precondition: zh-Hans has 'Invasion Voucher' = %r"
          % pl.get("Invasion Voucher"))
    check(pl.get("%@ Used!") == "已使用%@！",
          "and the tooltip template is already localised: %r" % pl.get("%@ Used!"))

print("\n== 8. earlier injections untouched ==")
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486)]}
for sub, ranges in FORBIDDEN.items():
    for lo, hi in ranges:
        a = old_sl[sub].addr_to_file(lo)
        b = old_sl[sub].addr_to_file(hi - 1) + 1
        check(old_sl[sub].data[a:b] == new_sl[sub].data[a:b],
              "sub%d %#x..%#x unchanged" % (sub, lo, hi))
for sub, addr in ((6, 0x195004), (9, 0x12980C)):
    a = old_sl[sub].addr_to_file(addr)
    check(old_sl[sub].data[a:a + 12] == new_sl[sub].data[a:a + 12],
          "sub%d %#x (v14 getCurrentLanguage) unchanged" % (sub, addr))
for sub, addrs in ((6, [0xB75AC, 0xB76D4, 0x7389C, 0x3371C, 0x33A34]),
                   (9, [0x86112, 0x86218, 0x26D90])):
    for a in addrs:
        o = old_sl[sub].addr_to_file(a)
        check(old_sl[sub].data[o:o + 4] == new_sl[sub].data[o:o + 4],
              "sub%d %#x (v15 retarget) unchanged" % (sub, a))

print("\n== 9. the corpse we buried the stub in is still a corpse ==")
selrefs = set()
sec = next(s for s in sl9.sections if s.name == "__objc_selrefs")
for off in range(0, sec.size, 4):
    v = struct.unpack_from("<I", sl9.data, sec.offset + off)[0]
    if v:
        o = sl9.addr_to_file(v)
        if o:
            e = sl9.data.find(b"\0", o, o + 200)
            if e > 0:
                selrefs.add(sl9.data[o:e].decode("utf-8", "replace"))
check("fadeOutAllButtons" not in selrefs,
      "-[ZFFightAbilityGUI fadeOutAllButtons] is still unreferenced by any selref")
txt = next(s for s in sl9.sections if s.name == "__text")
md2 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md2.detail = True
md2.skipdata = True
targets = set()
for i in md2.disasm(sl9.data[txt.offset:txt.offset + txt.size], txt.addr):
    if i.mnemonic in ("bl", "blx", "b") and i.operands and i.operands[0].type == 2:
        targets.add(i.operands[0].imm & ~1)
intruders = sorted(t for t in targets if STUB <= t < STUB + 37 and t != STUB)
check(not intruders,
      "nothing else branches into the 37 overwritten bytes (%s)"
      % [hex(t) for t in intruders])
check(STUB in targets, "and our new `bl %#x` is the only entrant" % STUB)

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

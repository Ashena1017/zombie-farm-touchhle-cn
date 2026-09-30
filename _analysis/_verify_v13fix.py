
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
"""Independent verifier for v13fix.  Does not import the patcher.

Everything here is re-derived from the two IPAs:
  * the byte diff must be confined to the 6 declared ranges
  * the two stubs must disassemble to the intended sequence
  * the 4 retarget sites must still set up r0/r1/r2/r3 the same way
  * the cave we occupy (`removeSeasonalQuests`) must be provably unreachable
  * `zfrLoc` at the address we call must really be the
    localizedStringForKey: helper
"""
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat          # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402
from capstone import (CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs)  # noqa: E402
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC)  # noqa: E402

ROOT = _PROJECT_ROOT / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
OLD = ROOT / f"{BASE}.fixed-fonts-v12fix.ipa"
NEW = ROOT / f"{BASE}.fixed-fonts-v13fix.ipa"
EXECUTABLE = "Payload/ZFR.app/ZFR"

FAIL = []


def check(cond, msg):
    if cond:
        print("  ok   %s" % msg)
    else:
        print("  FAIL %s" % msg)
        FAIL.append(msg)


def load(path):
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as z:
        exe = z.read(EXECUTABLE)
        bad = z.testzip()
    return raw, exe, bad


print("== 1. archive level ==")
old_raw, old_exe, old_bad = load(OLD)
new_raw, new_exe, new_bad = load(NEW)
check(len(old_raw) == len(new_raw) == 59564493,
      "both IPAs are %d bytes" % len(new_raw))
check(new_bad is None, "v13fix archive passes testzip()")
check(old_bad is None, "v12fix archive passes testzip()")
check(hashlib.sha256(new_raw).hexdigest().upper() ==
      "67B26EEB87F6BB7722985899FBA4382AB3EE1BC344093C9A0F26CE23EE7BC1AB",
      "v13fix sha256 matches the reported value")

print("\n== 2. FAT layout ==")
from patch_zfr_alert_fonts import fat_descriptors  # noqa: E402

d_old = {d["subtype"]: d for d in fat_descriptors(old_exe)}
d_new = {d["subtype"]: d for d in fat_descriptors(new_exe)}
old_sl = {s.subtype: s for s in parse_fat(old_exe)}
new_sl = {s.subtype: s for s in parse_fat(new_exe)}
check(set(old_sl) == set(new_sl) == {6, 9}, "both slices present: %s" % sorted(new_sl))
check([len(old_sl[k].data) for k in (6, 9)] == [len(new_sl[k].data) for k in (6, 9)],
      "slice sizes unchanged")
check(d_old == d_new, "FAT descriptors unchanged")

# ---------------------------------------------------------------- diff
EXPECTED = {
    (6, 0x16D594, 24, "stub (removeSeasonalQuests prologue)"),
    (6, 0x0B75AC, 4, "retarget CJK branch"),
    (6, 0x0B76D4, 4, "retarget default branch"),
    (9, 0x10C470, 22, "stub (removeSeasonalQuests prologue)"),
    (9, 0x086112, 4, "retarget CJK branch"),
    (9, 0x086218, 4, "retarget default branch"),
}
print("\n== 3. byte diff confinement ==")
changed = set()
diff_by_sub = {}
for sub in (6, 9):
    oa, na = old_sl[sub], new_sl[sub]
    n = min(len(oa.data), len(na.data))
    diff = [i for i in range(n) if oa.data[i] != na.data[i]]
    diff_by_sub[sub] = set(diff)

    def to_addr(off):
        for s in oa.sections:
            if s.offset <= off < s.offset + s.size:
                return s.addr + (off - s.offset)
        return None

    covered = set()
    for e_sub, addr, width, _note in EXPECTED:
        if e_sub != sub:
            continue
        a = oa.addr_to_file(addr)
        rng = set(range(a, a + width))
        hit = diff_by_sub[sub] & rng
        check(len(hit) > 0,
              "sub%d %#x +%d  %s  (bytes really changed)" % (sub, addr, width, _note))
        covered |= rng
    extra = diff_by_sub[sub] - covered
    check(not extra,
          "sub%d: no differing byte outside the declared ranges (%s)" %
          (sub, sorted(hex(to_addr(x)) for x in extra)))
    check(len(diff_by_sub[sub]) <= sum(e[2] for e in EXPECTED if e[0] == sub),
          "sub%d: %d differing bytes <= %d declared" %
          (sub, len(diff_by_sub[sub]),
           sum(e[2] for e in EXPECTED if e[0] == sub)))

# ---------------------------------------------------------------- stubs
print("\n== 4. stub semantics ==")
WANT = {
    6: ["push {r0, r1, r2, lr}", "mov r0, r5", "bl #0x1b6d0",
        "mov r3, r0", "pop {r0, r1, r2, lr}", "b #0x393fe0"],
    9: ["push {r0, r1, r2, lr}", "mov r0, r4", "bl #0x15140",
        "mov r3, r0", "pop.w {r0, r1, r2, lr}", "push {r4, lr}",
        "blx #0x2d014c", "pop {r4, pc}"],
}
STUB = {6: (0x16D594, 24), 9: (0x10C470, 22)}
for sub, (addr, width) in STUB.items():
    sl = new_sl[sub]
    o = sl.addr_to_file(addr)
    raw = sl.data[o:o + width]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    md.detail = True
    got = ["%s %s" % (i.mnemonic, i.op_str) for i in md.disasm(raw, addr)]
    check(got == WANT[sub], "sub%d stub disassembles exactly as intended" % sub)
    if got != WANT[sub]:
        print("       got  %s" % got)
        print("       want %s" % WANT[sub])
    check(not any("pc}" in g and "pop" in g and "pop.w" not in g
                  for g in got[:-1]),
          "sub%d stub has no mid-stub pop-to-pc" % sub)

# ---------------------------------------------------------------- call sites
print("\n== 5. retarget sites and their argument setup ==")
SITES = {6: [0x0B75AC, 0x0B76D4], 9: [0x086112, 0x086218]}
STUB_ADDR = {6: 0x16D594, 9: 0x10C470}
for sub, addrs in SITES.items():
    for addr in addrs:
        sl_o, sl_n = old_sl[sub], new_sl[sub]
        oo = sl_o.addr_to_file(addr)
        on = sl_n.addr_to_file(addr)
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
        md.detail = True
        old_i = list(md.disasm(sl_o.data[oo:oo + 4], addr))[0]
        new_i = list(md.disasm(sl_n.data[on:on + 4], addr))[0]
        check(old_i.mnemonic in ("bl", "blx") and
              int(old_i.op_str.lstrip('#'), 0) == (0x393FE0 if sub == 6 else 0x2D014C),
              "sub%d %#x originally called objc_msgSend" % (sub, addr))
        check(int(new_i.op_str.lstrip('#'), 0) == STUB_ADDR[sub],
              "sub%d %#x now calls the stub %#x (%s)" %
              (sub, addr, STUB_ADDR[sub], new_i.mnemonic))
        # 16 bytes of context before must be byte-identical
        check(sl_o.data[oo - 16:oo] == sl_n.data[on - 16:on],
              "sub%d %#x: 16 bytes of argument setup before the call unchanged" %
              (sub, addr))
        # the name register must still be loaded just before the call
        ctx = ["%s %s" % (i.mnemonic, i.op_str)
               for i in md.disasm(sl_o.data[oo - 24:oo], addr - 24)]
        reg = "r5" if sub == 6 else "r4"
        check(any(c == "mov r3, %s" % reg for c in ctx),
              "sub%d %#x: `mov r3, %s` (raw ability name) precedes the call" %
              (sub, addr, reg))
        # the next instruction after the call must be unchanged
        check(sl_o.data[oo + 4:oo + 12] == sl_n.data[on + 4:on + 12],
              "sub%d %#x: code after the call unchanged" % (sub, addr))

# ---------------------------------------------------------------- zfrLoc
print("\n== 6. the callee really is the localisation helper ==")
ZFRLOC = {6: (0x1B6D0, 0x4C), 9: (0x15140, 0x2C)}
for sub, (addr, width) in ZFRLOC.items():
    sl = new_sl[sub]
    o = sl.addr_to_file(addr)
    raw = sl.data[o:o + width]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    md.detail = True
    ins = list(md.disasm(raw, addr))

    def cstr(a):
        f = sl.addr_to_file(a)
        if f is None:
            return None
        try:
            e = sl.data.index(b"\0", f, f + 300)
        except ValueError:
            return None
        try:
            return sl.data[f:e].decode("utf-8")
        except Exception:
            return None

    def u32(a):
        f = sl.addr_to_file(a)
        return None if f is None else struct.unpack_from("<I", sl.data, f)[0]

    # resolve every pc-relative literal to the string it points at.
    # NOTE the base differs: ARM uses addr+8, Thumb LDR(literal) uses
    # Align(addr+4, 4) because Thumb instructions may sit at addr % 4 == 2.
    resolved = []
    for i in ins:
        if i.mnemonic == "ldr" and len(i.operands) == 2 and \
                i.operands[1].type == ARM_OP_MEM and \
                i.operands[1].mem.base == ARM_REG_PC:
            base = (i.address + 8) if sub == 6 else ((i.address + 4) & ~3)
            lit = base + (i.operands[1].mem.disp or 0)
            v = u32(lit)
            s = cstr(v) if v else None
            resolved.append((i.address, lit, v, s))

    def sec_of(v):
        for s in sl.sections:
            if s.addr <= v < s.addr + s.size:
                return s.name
        return None

    names = {r[3] for r in resolved if r[3]}
    check("mainBundle" in names,
          "sub%d %#x loads the `mainBundle` selector (%s)" % (sub, addr, sorted(names)))
    check("localizedStringForKey:value:table:" in names,
          "sub%d %#x loads the `localizedStringForKey:value:table:` selector" %
          (sub, addr))
    check(all(sec_of(r[2]) in ("__objc_methname", "__objc_selrefs", "__cstring")
              for r in resolved if r[2] and r[3]),
          "sub%d %#x: every resolved literal points at a name/selector string" %
          (sub, addr))
    text = ["%s %s" % (i.mnemonic, i.op_str) for i in ins]
    check(any(t.startswith("push") for t in text) and
          any(t.startswith("pop") or t.startswith("bx") for t in text),
          "sub%d %#x is a well-formed leaf helper" % (sub, addr))
    # the helper must move its single argument into both the key and value slots
    check(sum(1 for t in text if t.replace("movs", "mov").startswith("mov r3, r")
              or t.replace("movs", "mov").startswith("mov r2, r")) >= 2,
          "sub%d %#x passes the argument as both key and value" % (sub, addr))

# ---------------------------------------------------------------- dead cave
print("\n== 7. the occupied cave is unreachable (re-proved on the NEW binary) ==")
for sub in (6, 9):
    sl = new_sl[sub]
    o = sl.addr_to_file(0x16D594 if sub == 6 else 0x10C470)

    def cs_(a):
        f = sl.addr_to_file(a)
        if f is None:
            return None
        try:
            e = sl.data.index(b"\0", f, f + 300)
        except ValueError:
            return None
        try:
            return sl.data[f:e].decode("utf-8")
        except Exception:
            return None

    def u32(a):
        f = sl.addr_to_file(a)
        return None if f is None else struct.unpack_from("<I", sl.data, f)[0]

    in_selrefs = False
    for sec in sl.sections:
        if sec.name != "__objc_selrefs":
            continue
        for off in range(0, sec.size, 4):
            v = u32(sec.addr + off)
            if v and cs_(v) == "removeSeasonalQuests":
                in_selrefs = True
    check(not in_selrefs,
          "sub%d: `removeSeasonalQuests` never appears in __objc_selrefs "
          "-> no objc_msgSend can reach the cave" % sub)

    raw_count = sl.data.count(b"removeSeasonalQuests")
    check(raw_count == 1,
          "sub%d: the string occurs %d time(s) in the slice (__objc_methname only)"
          % (sub, raw_count))

    # no branch targets the entry
    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    md.detail = True
    md.skipdata = True
    entry = 0x16D594 if sub == 6 else 0x10C470
    hits = 0
    callers = 0
    for i in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if not i.id or not i.operands:
            continue
        if i.mnemonic not in ("bl", "blx", "b"):
            continue
        if i.operands[0].type != ARM_OP_IMM:
            continue
        if (i.operands[0].imm & ~1) != entry:
            continue
        hits += 1
        if i.mnemonic in ("bl", "blx"):
            callers += 1
    check(hits == callers == 2,
          "sub%d: exactly 2 callers and 0 plain branches target the cave entry %#x "
          "(hits=%d callers=%d)" % (sub, entry, hits, callers))

# ---------------------------------------------------------------- untouched
print("\n== 8. previously injected code untouched ==")
FORBIDDEN = {6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C)],
             9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C)]}
for sub, ranges in FORBIDDEN.items():
    for lo, hi in ranges:
        a = old_sl[sub].addr_to_file(lo)
        b = old_sl[sub].addr_to_file(hi - 1) + 1
        check(old_sl[sub].data[a:b] == new_sl[sub].data[a:b],
              "sub%d %#x..%#x unchanged" % (sub, lo, hi))

print("\n== 9. v12fix's stopListening rewrite is carried over intact ==")
for sub, addr in ((6, 0x16A5F8), (9, 0x10A1DC)):
    a = new_sl[sub].addr_to_file(addr)
    n = 64
    check(old_sl[sub].data[a:a + n] == new_sl[sub].data[a:a + n],
          "sub%d %#x..%#x identical to v12fix" % (sub, addr, addr + n))

print()
if FAIL:
    print("VERIFICATION FAILED (%d check(s))" % len(FAIL))
    for f in FAIL:
        print("   - %s" % f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

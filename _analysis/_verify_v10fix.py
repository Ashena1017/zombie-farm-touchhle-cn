"""INDEPENDENT verifier for fixed-fonts-v10fix.ipa.

Does not import the patcher.  Re-derives the byte diff between v6 and v10fix,
asserts it is exactly the 12 intended sites, and disassembles each site with a
few instructions of context so the resulting code can be eyeballed.
"""

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
import sys, pathlib, zipfile, hashlib
pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

ROOT = _PROJECT_ROOT / "zombie_farm_ipa"
A = ROOT / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v6.ipa"
B = ROOT / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v10fix.ipa"
EXE = "Payload/ZFR.app/ZFR"

EXPECT = {
    6: [(0x186D40, 4), (0x186D44, 4), (0x186D50, 4),
        (0x187DCC, 4), (0x187DD0, 4), (0x187DD8, 4)],
    9: [(0x11F43A, 2), (0x11F43C, 4), (0x11F440, 2),
        (0x120030, 2), (0x120032, 4), (0x120038, 2)],
}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


with zipfile.ZipFile(A) as z:
    ea = z.read(EXE)
with zipfile.ZipFile(B) as z:
    eb = z.read(EXE)
    names_a = sorted(z.namelist())

with zipfile.ZipFile(A) as z:
    names_b = sorted(z.namelist())

print("v6     exe sha256 =", hashlib.sha256(ea).hexdigest())
print("v10fix exe sha256 =", hashlib.sha256(eb).hexdigest())
print("same member list  =", names_a == names_b, "(%d members)" % len(names_a))
print("same exe size     =", len(ea) == len(eb), len(ea))
print()

sa = {s.subtype: s for s in parse_fat(ea)}
sb = {s.subtype: s for s in parse_fat(eb)}

ok = True

# 1. every expected site really differs, and decodes as intended
for sub, sites in EXPECT.items():
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    slab, snew = sa[sub], sb[sub]
    print("=== sub%d ===" % sub)
    for addr, n in sites:
        oa = slab.addr_to_file(addr)
        ob = snew.addr_to_file(addr)
        ra, rb = slab.data[oa:oa + n], snew.data[ob:ob + n]
        if ra == rb:
            print("  0x%08x  UNCHANGED  <-- FAIL" % addr)
            ok = False
            continue
        for label, raw in (("old", ra), ("new", rb)):
            ins = list(md.disasm(raw, addr))
            txt = ("%s %s" % (ins[0].mnemonic, ins[0].op_str)) if ins else "<undecoded>"
            print("  0x%08x  %-5s %-10s %s" % (addr, label, raw.hex(), txt))
    print()

# 2. the diff between v6 and v10fix must be EXACTLY those ranges
want = set()
for sub, sites in EXPECT.items():
    slab = sa[sub]
    for addr, n in sites:
        off = slab.addr_to_file(addr)
        for i in range(off, off + n):
            want.add((sub, i))

diff = set()
for sub in (6, 9):
    da, db = sa[sub].data, sb[sub].data
    if len(da) != len(db):
        print("FAIL: sub%d size differs" % sub)
        ok = False
        continue
    for i in range(len(da)):
        if da[i] != db[i]:
            diff.add((sub, i))

print("diff bytes: %d   (site bytes: %d - identical-within-site bytes)"
      % (len(diff), len(want)))
extra = sorted(diff - want)
if extra:
    print("FAIL: changes outside the 12 intended sites:",
          [(s, hex(a)) for s, a in extra][:20])
    ok = False
else:
    print("OK: every changed byte lies inside one of the 12 intended sites")
if len(diff) == 0:
    print("FAIL: nothing changed at all")
    ok = False

# 3. helper cave regions untouched
for sub, (lo, hi) in ((6, (0x1B464, 0x1B810)), (9, (0x14F6C, 0x151C0))):
    a0 = sa[sub].addr_to_file(lo)
    a1 = sa[sub].addr_to_file(hi - 1) + 1
    same = sa[sub].data[a0:a1] == sb[sub].data[a0:a1]
    print("helper region sub%d %#x..%#x intact = %s" % (sub, lo, hi, same))
    ok = ok and same

print()
print("RESULT:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)

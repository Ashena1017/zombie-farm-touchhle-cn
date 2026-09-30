"""INDEPENDENT verifier for fixed-fonts-v11fix.ipa.

Does not import the patcher.  Re-derives the byte diff between v6 and v11fix,
asserts every changed byte lies inside a declared range, disassembles the two
rewritten stopListening methods, and confirms the helper caves are untouched.
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
B = ROOT / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v11fix.ipa"
EXE = "Payload/ZFR.app/ZFR"

# declared (lo, hi) address ranges that are allowed to differ
ALLOWED = {
    6: [(0x16A5F8, 0x16A70C), (0x186D40, 0x186D48), (0x186D50, 0x186D54),
        (0x187DCC, 0x187DD4), (0x187DD8, 0x187DDC)],
    9: [(0x10A1DC, 0x10A29C), (0x11F43A, 0x11F442), (0x120030, 0x12003A)],
}

with zipfile.ZipFile(A) as z:
    ea = z.read(EXE)
    na = sorted(z.namelist())
with zipfile.ZipFile(B) as z:
    eb = z.read(EXE)
    nb = sorted(z.namelist())

print("v6     exe sha256 =", hashlib.sha256(ea).hexdigest())
print("v11fix exe sha256 =", hashlib.sha256(eb).hexdigest())
print("same member list  =", na == nb, "(%d members)" % len(na))
print("same exe size     =", len(ea) == len(eb), len(ea))
print()

sa = {s.subtype: s for s in parse_fat(ea)}
sb = {s.subtype: s for s in parse_fat(eb)}
ok = True

# ---- 1. diff confinement
for sub in (6, 9):
    da, db, sl = sa[sub].data, sb[sub].data, sa[sub]
    if len(da) != len(db):
        print("FAIL: sub%d size differs" % sub)
        ok = False
        continue
    allow = set()
    for lo, hi in ALLOWED[sub]:
        a0 = sl.addr_to_file(lo)
        a1 = sl.addr_to_file(hi - 1) + 1
        allow.update(range(a0, a1))
    diff = {i for i in range(len(da)) if da[i] != db[i]}
    extra = sorted(diff - allow)
    print("sub%d: %d changed bytes, %d outside declared ranges"
          % (sub, len(diff), len(extra)))
    if extra:
        print("   FAIL first offenders:", [(sub, hex(sl.file_to_addr(i)))
                                           for i in extra[:10]])
        ok = False
    if not diff:
        print("   FAIL nothing changed in sub%d" % sub)
        ok = False
print()

# ---- 2. disassemble the rewritten stopListening methods
for sub, lo, length in ((6, 0x16A5F8, 0x40), (9, 0x10A1DC, 0x38)):
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    off = sb[sub].addr_to_file(lo)
    raw = sb[sub].data[off:off + length]
    print("=== sub%d new stopListening body @%#x ===" % (sub, lo))
    for i in md.disasm(raw, lo):
        print("   %#010x  %-10s %s %s" % (i.address, i.bytes.hex(), i.mnemonic, i.op_str))
    print()

# ---- 3. helper caves untouched
for sub, (lo, hi) in ((6, (0x1B464, 0x1B810)), (9, (0x14F6C, 0x151C0))):
    a0 = sa[sub].addr_to_file(lo)
    a1 = sa[sub].addr_to_file(hi - 1) + 1
    same = sa[sub].data[a0:a1] == sb[sub].data[a0:a1]
    print("helper region sub%d %#x..%#x intact = %s" % (sub, lo, hi, same))
    ok = ok and same

print()
print("RESULT:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)

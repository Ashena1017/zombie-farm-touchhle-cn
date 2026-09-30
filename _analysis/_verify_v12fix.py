"""INDEPENDENT verifier for fixed-fonts-v12fix.ipa.

Re-derives the byte diff between v6 and v12fix, asserts every changed byte lies
inside a declared range, disassembles the rewritten stopListening methods AND
the four factory patch sites with context (so the r0 handoff that v11fix broke
is visible), and confirms the helper caves are untouched.
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
B = ROOT / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa"
EXE = "Payload/ZFR.app/ZFR"

ALLOWED = {
    6: [(0x16A5F8, 0x16A70C), (0x186D40, 0x186D48), (0x186D50, 0x186D54),
        (0x187DCC, 0x187DD4), (0x187DD8, 0x187DDC)],
    9: [(0x10A1DC, 0x10A29C), (0x11F43A, 0x11F442), (0x120030, 0x12003A)],
}

# factory sites: show 3 instructions starting here in the PATCHED build
CONTEXT = {
    6: [(0x187DC8, 0x18), (0x186D3C, 0x18)],
    9: [(0x12002C, 0x18), (0x11F434, 0x18)],
}

with zipfile.ZipFile(A) as z:
    ea = z.read(EXE)
    na = sorted(z.namelist())
with zipfile.ZipFile(B) as z:
    eb = z.read(EXE)
    nb = sorted(z.namelist())

print("v6     exe sha256 =", hashlib.sha256(ea).hexdigest())
print("v12fix exe sha256 =", hashlib.sha256(eb).hexdigest())
print("same member list  =", na == nb, "(%d members)" % len(na))
print("same exe size     =", len(ea) == len(eb), len(ea))
print()

sa = {s.subtype: s for s in parse_fat(ea)}
sb = {s.subtype: s for s in parse_fat(eb)}
ok = True

for sub in (6, 9):
    da, db, sl = sa[sub].data, sb[sub].data, sa[sub]
    allow = set()
    for lo, hi in ALLOWED[sub]:
        allow.update(range(sl.addr_to_file(lo), sl.addr_to_file(hi - 1) + 1))
    diff = {i for i in range(len(da)) if da[i] != db[i]}
    extra = sorted(diff - allow)
    print("sub%d: %d changed bytes, %d outside declared ranges"
          % (sub, len(diff), len(extra)))
    if extra or not diff:
        ok = False
        print("   FAIL", [(sub, hex(sl.file_to_addr(i))) for i in extra[:8]])
print()

for sub, lo, length, title in (
        (6, 0x16A5F8, 0x40, "new stopListening body"),
        (9, 0x10A1DC, 0x38, "new stopListening body")):
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    off = sb[sub].addr_to_file(lo)
    print("=== sub%d %s @%#x ===" % (sub, title, lo))
    for i in md.disasm(sb[sub].data[off:off + length], lo):
        print("   %#010x  %-10s %s %s" % (i.address, i.bytes.hex(), i.mnemonic, i.op_str))
    print()

for sub, ranges in CONTEXT.items():
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    for lo, length in ranges:
        off = sb[sub].addr_to_file(lo)
        print("=== sub%d factory context @%#x (patched) ===" % (sub, lo))
        for i in md.disasm(sb[sub].data[off:off + length], lo):
            print("   %#010x  %-10s %s %s" % (i.address, i.bytes.hex(), i.mnemonic, i.op_str))
        print()

for sub, (lo, hi) in ((6, (0x1B464, 0x1B810)), (9, (0x14F6C, 0x151C0))):
    a0, a1 = sa[sub].addr_to_file(lo), sa[sub].addr_to_file(hi - 1) + 1
    same = sa[sub].data[a0:a1] == sb[sub].data[a0:a1]
    print("helper region sub%d %#x..%#x intact = %s" % (sub, lo, hi, same))
    ok = ok and same

print()
print("RESULT:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)

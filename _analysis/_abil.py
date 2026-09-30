"""Map the ability-name data path:
  - every __cstring / CFString matching 'Unlocked a new %@ ability!'
  - the method -getRandomAbilityToUnlock in both slices
  - every bl / blx that targets it
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
import sys, zipfile, struct, bisect
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
WANT = "Unlocked a new"

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    def cs_(a):
        o = sl.addr_to_file(a)
        if o is None:
            return None
        try:
            e = sl.data.index(b"\0", o, o + 400)
        except ValueError:
            return None
        try:
            return sl.data[o:e].decode("utf-8")
        except Exception:
            return None

    print("\n########## sub%d ##########" % sub)
    # 1. cstring occurrences
    cs_hits = []
    for sec in sl.sections:
        if sec.name != "__cstring":
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        s = 0
        while True:
            i = blob.find(WANT.encode(), s)
            if i < 0:
                break
            cs_hits.append(sec.addr + i)
            s = i + 1
    print("cstring hits: %s" % [hex(h) for h in cs_hits])
    for h in cs_hits:
        print("    %#x  %r" % (h, cs_(h)))

    # 2. cfstring whose data points at those
    cf_objs = []
    for sec in sl.sections:
        if sec.name not in ("__cfstring", "__objc_cfstring"):
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v in cs_hits:
                cf_objs.append((sec.name, a, v))
    print("cfstring data fields: %s" % [(n, hex(a)) for n, a, v in cf_objs])
    cf_addr = [a - 8 for _n, a, _v in cf_objs]
    print("=> CFString objects: %s" % [hex(x) for x in cf_addr])

    # 3. code refs to those CFString objects (literal pools inside __text)
    txt = next(s for s in sl.sections if s.name == "__text")
    for i in range(txt.size // 4):
        a = txt.addr + i * 4
        v = u32(a)
        if v in cf_addr:
            print("   __text literal @ %#x = %#x  (CFString)" % (a, v))

    # 4. method lookup
    cb = classes_by_name(sl)
    full = {}
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append((cn, m.selector, m.imp))
    starts = sorted(full)
    tgt = []
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if "Ability" in (m.selector or "") or "ability" in (m.selector or ""):
                print("   METHOD %-28s %-46s imp=%s" % (cn, m.selector, hex(m.imp) if m.imp else None))
                if m.imp:
                    tgt.append(m.imp & ~1)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if not ins.id or not ins.operands:
            continue
        if ins.mnemonic not in ("bl", "blx"):
            continue
        o = ins.operands[0]
        if o.type != ARM_OP_IMM:
            continue
        t = o.imm & ~1
        if t in tgt:
            j = bisect.bisect_right(starts, ins.address) - 1
            where = "%s %s+%#x" % (full[starts[j]][0][0], full[starts[j]][0][1], ins.address - starts[j]) if j >= 0 else "?"
            print("   CALL %#x -> %#x   in %s" % (ins.address, t, where))

"""Who defines +abilitiesToUnlockForTier: and what does -newAbilityIconClicked: do?"""

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

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v13fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

WANT_SEL = ("abilitiesToUnlockForTier:", "flagBit", "abilityFlags", "setAbilityFlags:",
            "newAbilityIconClicked:", "cleanupNewAbilityMenu:", "getRandomAbilityToUnlock")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    def cs_(a):
        o = sl.addr_to_file(a)
        if o is None:
            return None
        try:
            e = sl.data.index(b"\0", o, o + 300)
        except ValueError:
            return None
        try:
            return sl.data[o:e].decode("utf-8")
        except Exception:
            return None

    cb = classes_by_name(sl)
    print("\n########## sub%d  (%d classes)" % (sub, len(cb)))
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.selector in WANT_SEL:
                kind = "class" if m.kind == "class" else "inst "
                print("   %-5s %-22s %-34s imp=%s" %
                      (kind, cn, m.selector, hex(m.imp) if m.imp else None))
    if sub == 6:
        # resolve classref used at 0xb7134 (r4 <- __objc_classrefs slot)
        lit = 0xB712C + 8 + 0xF78
        slot = u32(lit)
        # slot is a delta-consumer: ldr r2,[pc,#0xf78] gives the delta, add? no -
        # actual pattern: r2 = literal; ldr r4,[pc,r2]
        d = slot
        eff = (0xB7134 + 8 + d) & 0xffffffff
        cls = u32(eff)
        print("\n   classref slot = %#x, class_t = %#x" % (eff, cls or 0))
        # find the class by address
        for cn, (c, info) in cb.items():
            if getattr(c, "addr", None) == cls:
                print("   => class is %s" % cn)
        # fall back: read class_ro name
        data = u32(cls + 16) if cls else None
        name_ptr = u32(data + 16) if data else None
        print("   class_ro=%s name_ptr=%s name=%r" %
              (hex(data) if data else None, hex(name_ptr) if name_ptr else None,
               cs_(name_ptr) if name_ptr else None))

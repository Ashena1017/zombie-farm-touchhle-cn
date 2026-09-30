"""Find every code site that loads the abilityFlags / setAbilityFlags: selrefs and
disassemble the surrounding method context."""

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
WANT_SLOTS = {6: {0x459008: "abilityFlags", 0x45A5D4: "setAbilityFlags:"},
              9: {0x394F90: "abilityFlags", 0x39655C: "setAbilityFlags:"}}

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    cb = classes_by_name(sl)
    full = {}
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append(cn + " " + m.selector)
    starts = sorted(full)

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        return "%s+%#x" % (full[starts[i]][0], a - starts[i]) if i >= 0 else "?"

    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM if sub == 6 else CS_MODE_THUMB)
    md.detail = True
    md.skipdata = True
    slots = WANT_SLOTS[sub]

    print("\n########## sub%d" % sub)
    # scan __text literals for the deltas, then find the consumers
    found = []
    for i in range(txt.size // 4):
        a = txt.addr + i * 4
        v = u32(a)
        if v is None:
            continue
        # the delta idiom: literal D such that (consume+8) + D == slot
        for slot, name in slots.items():
            # ARM: consume at a-4 or a-8 typically
            for cons in (a - 4, a - 8):
                base = cons + (8 if sub == 6 else 4)
                if sub == 9:
                    base = (cons + 4) & ~3
                if ((base + v) & 0xFFFFFFFF) == slot:
                    found.append((cons, a, slot, name))
                    break
    for cons, lit, slot, name in sorted(set(found)):
        print("   %-18s consumer=%#010x literal@%#010x  %s" % (name, cons, lit, owner(cons)))

    # also: print the method unlockActorSpecificAbilities
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.selector in ("unlockActorSpecificAbilities", "newAbilityIconClicked:"):
                imp = m.imp & ~1
                print("\n   === %s -%s @ %#x ===" % (cn, m.selector, imp))
                o = sl.addr_to_file(imp)
                ins = list(md.disasm(sl.data[o:o + 120], imp))
                for i in ins:
                    print("      %#010x  %-9s %s" % (i.address, i.mnemonic, i.op_str))

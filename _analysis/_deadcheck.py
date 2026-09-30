"""Verify whether specific selectors are ever SENT (i.e. present in __objc_selrefs)
and whether specific addresses are branch targets."""

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
import sys, zipfile, struct
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
SELS = ["removeSeasonalQuests", "addSeasonalQuests", "checkSeason",
        "displayMessage:atPosition:withColor:withDelay:withScroll:withScale:",
        "stringWithFormat:", "getRandomAbilityToUnlock", "fadeOutAllButtons",
        "printEvents", "backupSaveFiles"]
ADDRS = [0x16d594, 0x16d3f8, 0x1ebcc]

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

    print("\n########## sub%d" % sub)
    # raw byte occurrences anywhere in the slice
    for s in SELS:
        print("   raw count %-70s %d" % (s, sl.data.count(s.encode())))
    # selrefs
    selref_names = set()
    for sec in sl.sections:
        if sec.name != "__objc_selrefs":
            continue
        for off in range(0, sec.size, 4):
            v = u32(sec.addr + off)
            if v:
                t = cs_(v)
                if t:
                    selref_names.add(t)
    for s in SELS:
        print("   in __objc_selrefs  %-70s %s" % (s, s in selref_names))
    # branch targets
    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    tg = set()
    for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if ins.id and ins.operands and ins.mnemonic in ("bl", "blx", "b") and ins.operands[0].type == ARM_OP_IMM:
            t = ins.operands[0].imm & ~1
            if txt.addr <= t < txt.addr + txt.size:
                tg.add(t)
    for a in ADDRS:
        hits = [x for x in tg if x == a]
        print("   branch target %#x  %s" % (a, bool(hits)))

"""Find the code that reads the 'seasonalDate' / 'seasonal' plist keys and any
branch into the addSeasonalQuests / checkSeason selectors."""

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
import sys, pathlib, struct, zipfile
pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

IPA = pathlib.Path(__file__).resolve().parent / str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
with zipfile.ZipFile(IPA) as z:
    data = z.read("Payload/ZFR.app/ZFR")


def u32(sl, a):
    o = sl.addr_to_file(a)
    return struct.unpack_from("<I", sl.data, o)[0] if o is not None else None


def cstr(sl, a):
    return sl.cstr(a) if a else None


for want in ("seasonalDate", "seasonal"):
    print("### key %r" % want)
    for sub in (6, 9):
        sl = [s for s in parse_fat(data) if s.subtype == sub][0]
        # find the cstring
        hits = []
        for s in sl.sections:
            if s.name != "__cstring":
                continue
            blob = sl.data[s.offset:s.offset + s.size]
            start = 0
            while True:
                i = blob.find(want.encode() + b"\x00", start)
                if i < 0:
                    break
                hits.append(s.addr + i)
                start = i + 1
        print("  sub%d __cstring occurrences: %s" % (sub, [hex(h) for h in hits]))
        # find cfstring whose data pointer == that cstring, then find code refs to the cfstring
        cfsec = next((s for s in sl.sections if s.name == "__cfstring"), None)
        objsec = next((s for s in sl.sections if s.name == "__objc_cfstring"), None)
        targets = []
        for sec in (cfsec, objsec):
            if not sec:
                continue
            for i in range(sec.size // 4):
                a = sec.addr + i * 4
                v = u32(sl, a)
                if v in hits:
                    # the actual CFString object starts 8 or 12 bytes earlier typically
                    targets.append((sec.name, a, v))
        print("  cfstring-ish refs: %s" % [(n, hex(a), hex(v)) for n, a, v in targets])

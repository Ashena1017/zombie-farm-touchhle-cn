
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
import zipfile, plistlib, struct, sys, re
pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
NAMES = ["Zombie", "Girl Zombie", "ZomBumpkin", "Headless Zombie", "Garden Zombie", "Zyborg",
         "ZomBeauty", "ZomBruiser", "Kindlehead", "ZomBotanist", "Zombot", "Amazombie",
         "ZomBrute", "Flamehead", "Flower Zombie", "ZomGoblin", "Robo Zombie", "Zombielocks",
         "Zombarian", "Party Zombie", "Zombee", "Imp Zombie", "zombie"]

z = zipfile.ZipFile(IPA)
# 1) zh-Hans Localizable.strings entries
pl = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
print("=== zh-Hans Localizable.strings ===")
for n in NAMES:
    print("  %-18s %r" % (n, pl.get(n, "<MISSING>")))

# 2) any of the Chinese values present as UTF-8 bytes inside the binary?
d = z.read("Payload/ZFR.app/ZFR")
print("\n=== Chinese ability names inside the ZFR binary ===")
for n in NAMES:
    v = pl.get(n)
    if not v:
        continue
    b = v.encode("utf-8")
    print("  %-18s %-14s count=%d" % (n, v, d.count(b)))

# 3) is ANY CJK present in the binary at all?
cjk = re.findall(rb"(?:[\xe4-\xe9][\x80-\xbf]{2}){2,}", d)
print("\n  CJK runs in binary: %d, distinct: %d" % (len(cjk), len(set(cjk))))
for s in list(dict.fromkeys(cjk))[:40]:
    try:
        print("     %r" % s.decode("utf-8"))
    except Exception:
        pass

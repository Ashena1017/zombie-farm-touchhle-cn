
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
import zipfile, plistlib, re

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
z = zipfile.ZipFile(IPA)


def load(name):
    d = z.read(name)
    try:
        return plistlib.loads(d)
    except Exception:
        pass
    # old-style ASCII plist -> use plutil-ish naive parse
    return None


for lp in ("English.lproj", "zh-Hans.lproj"):
    name = "Payload/ZFR.app/%s/Localizable.strings" % lp
    d = z.read(name)
    try:
        pl = plistlib.loads(d)
    except Exception as e:
        print("%s: not a plist (%s)" % (name, e))
        txt = d.decode("utf-16", "replace") if d[:2] in (b"\xff\xfe", b"\xfe\xff") else d.decode("utf-8", "replace")
        for line in txt.splitlines():
            if re.search(r"Easter|Badger|Dairy King|Uberbiss|Brain Freeze|Halloween|Blizzard|Count ", line):
                print("   ", line.strip()[:200])
        continue
    print("=== %s ===" % name)
    for k, v in pl.items():
        if re.search(r"Easter|Badger|Dairy King|Uberbiss|Brain Freeze|Halloween|Blizzard", k + str(v)):
            print("   %-30r -> %r" % (k, v))

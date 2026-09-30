
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
import zipfile, sys, io

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
TERMS = [b"Badger", b"Dairy King", b"Uberbiss", b"Easter", b"Brain Freeze", b"Halloween",
         b"quest_icon_easter", b"quest_icon_brainfreeze", b"quest_icon_halloween"]
z = zipfile.ZipFile(IPA)
hits = {}
for n in z.namelist():
    if n.endswith("/"):
        continue
    try:
        d = z.read(n)
    except Exception:
        continue
    for t in TERMS:
        if t in d:
            hits.setdefault(t.decode(), []).append(n)
for t in TERMS:
    k = t.decode()
    lst = hits.get(k, [])
    print("%-22s %d file(s)" % (k, len(lst)))
    for f in sorted(lst)[:12]:
        print("      %s" % f)
    if len(lst) > 12:
        print("      ... +%d" % (len(lst) - 12))

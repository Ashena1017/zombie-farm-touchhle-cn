
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
z = zipfile.ZipFile(IPA)

# 1) stage names present as strings in the binary?
terms = [b"EasterStage", b"Halloween2011Stage", b"IceCreamStage", b"ValentinesStage2012",
         b"Easter Badger", b"Dairy King", b"Count von Uberbiss"]
for sub in (6, 9):
    sl = next(s for s in parse_fat(z.read("Payload/ZFR.app/ZFR")) if s.subtype == sub)
    found = []
    for s in sl.sections:
        if s.name not in ("__cstring", "__objc_methname", "__ustring"):
            continue
        blob = sl.data[s.offset:s.offset + s.size]
        for t in terms:
            if t + b"\x00" in blob:
                found.append(t.decode())
    print("sub%d binary strings: %s" % (sub, sorted(set(found))))

# 2) which plists mention the seasonal stage names?
for n in sorted(z.namelist()):
    if not n.lower().endswith(".plist") or n.endswith("CodeResources"):
        continue
    d = z.read(n)
    for t in (b"EasterStage", b"Halloween2011Stage", b"IceCreamStage"):
        if t in d:
            print("plist %s mentions %s" % (n, t.decode()))

# 3) Promos.plist / Market.plist seasonal gating keys
for n in ("Payload/ZFR.app/Promos.plist", "Payload/ZFR.app/Market.plist",
          "Payload/ZFR.app/GiftSelection.plist", "Payload/ZFR.app/Drops.plist",
          "Payload/ZFR.app/TileProperties.plist"):
    try:
        pl = plistlib.loads(z.read(n))
    except Exception as e:
        print("%s: %s" % (n, e))
        continue
    blob = repr(pl)
    keys = sorted(set(re.findall(r"'(\w*[Ss]eason\w*)'", blob)))
    print("%s: seasonal-ish keys = %s ; 'Easter' count=%d 'Halloween' count=%d 'BrainFreeze' count=%d"
          % (n.rsplit("/", 1)[-1], keys, blob.count("Easter"), blob.count("Halloween"), blob.count("BrainFreeze")))

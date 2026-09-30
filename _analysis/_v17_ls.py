import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
PATS = [p.lower() for p in (sys.argv[1:] or ["dismissedpositive"])]
CLS = None

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    cb = classes_by_name(sl)
    print("\n=== sub%d" % sub)
    for cn, (c, info) in sorted(cb.items()):
        for m in all_methods(sl, c, info):
            if any(p in m.selector.lower() for p in PATS):
                print("   %-22s %-60s imp=%#010x" % (cn, m.selector, m.imp))

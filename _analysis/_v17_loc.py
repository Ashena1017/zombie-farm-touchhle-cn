"""v17 recon C: Localizable.strings lookups + a sanity dump of the CJK pool."""
import plistlib
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
NEEDLES = sys.argv[1:] or ["Invasion", "入侵", "Used"]

with zipfile.ZipFile(IPA) as z:
    names = [n for n in z.namelist() if n.endswith("Localizable.strings")]
    print("lproj members: %s" % names)
    for n in names:
        pl = plistlib.loads(z.read(n))
        hit = {k: v for k, v in pl.items()
               if any(s.lower() in k.lower() or s.lower() in str(v).lower() for s in NEEDLES)}
        print("\n=== %s : %d/%d entries match %r" % (n, len(hit), len(pl), NEEDLES))
        for k, v in sorted(hit.items()):
            print("    %-42r -> %r" % (k, v))

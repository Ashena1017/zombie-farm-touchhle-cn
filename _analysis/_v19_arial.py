"""v19 recon B: the Arial-BoldMT.strings table vs the untouched baseline."""
import plistlib
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())

CUR = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v18fix.ipa"
BASE = ROOT / "zombie_farm_ipa/ZFR 1.0.zh-CN-unsigned.ipa"

with zipfile.ZipFile(CUR) as z:
    cur_names = [n for n in z.namelist() if n.endswith(".strings")]
with zipfile.ZipFile(BASE) as z:
    base_names = [n for n in z.namelist() if n.endswith(".strings")]

print("== .strings members ==")
print("  current : %s" % "\n            ".join(cur_names))
print("  baseline: %s" % "\n            ".join(base_names))

with zipfile.ZipFile(CUR) as z:
    cur = {n: z.read(n) for n in cur_names}
with zipfile.ZipFile(BASE) as z:
    base = {n: z.read(n) for n in base_names}

for n in sorted(set(cur) | set(base)):
    print("\n" + "=" * 74)
    print(n)
    print("=" * 74)
    c = cur.get(n)
    b = base.get(n)
    print("  sizes: current=%s baseline=%s" % (len(c) if c else "-", len(b) if b else "-"))
    pc = pb = None
    try:
        pc = plistlib.loads(c) if c else None
    except Exception as e:
        print("  current is not a plist: %s" % e)
    try:
        pb = plistlib.loads(b) if b else None
    except Exception as e:
        print("  baseline is not a plist: %s" % e)
    if isinstance(pb, dict) and isinstance(pc, dict):
        print("  entries: baseline=%d current=%d" % (len(pb), len(pc)))
        missing = sorted(set(pb) - set(pc))
        added = sorted(set(pc) - set(pb))
        if missing:
            print("  KEYS LOST: %r" % missing)
        if added:
            print("  KEYS ADDED: %r" % added)
        for k in sorted(set(pb) | set(pc)):
            bv, cv = pb.get(k, "<MISSING>"), pc.get(k, "<MISSING>")
            flag = "   " if bv == cv else " * "
            print("  %s%-34r" % (flag, k))
            print("      base %r" % (bv,))
            if bv != cv:
                print("      cur  %r" % (cv,))

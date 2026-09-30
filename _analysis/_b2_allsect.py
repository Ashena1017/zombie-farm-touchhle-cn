"""Where do the interesting format strings live?  The mojibake ones turned out to
be in __const, so scan EVERY section (not just __cstring) in both slices."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v15fix.ipa"
WANTED = [b"%@ Used!", b"%@ (%i)        ", b"%@ (%i)            ", b"%@ (%i)",
          b"+%ig", b"+%ixp", b"+%dxp", b"-%ig", b"%d gold", b"%i xp", b"%i gold"]

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    print("\n" + "=" * 74)
    print("sub%d" % sub)
    print("=" * 74)
    for pat in WANTED:
        hits = []
        for sec in sl.sections:
            if sec.size == 0 or sec.offset == 0:
                continue
            blob = sl.data[sec.offset:sec.offset + sec.size]
            start = 0
            while True:
                i = blob.find(pat, start)
                if i < 0:
                    break
                # must be NUL-terminated (i.e. a real C string) and start-ish aligned
                end = blob.find(b"\0", i)
                hits.append((sec.name, sec.addr + i, blob[i:end].decode("utf-8", "replace")))
                start = i + 1
        print("  %-22r %d hit(s)" % (pat.decode(), len(hits)))
        for name, addr, text in hits:
            print("       %-14s %#010x  %r" % (name, addr, text))

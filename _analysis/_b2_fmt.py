"""Look for the floating-text format strings ("+%i..." etc.) in __cstring."""
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6,):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    for sec in sl.sections:
        if sec.name != "__cstring":
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        p = 0
        print("=== entries containing '+' and a format spec ===")
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            try:
                s = blob[p:e].decode("utf-8")
            except Exception:
                s = None
            if s and "%" in s and ("+" in s or "gold" in s.lower() or "exp" in s.lower()
                                   or "xp" in s.lower()):
                print("   %#010x  %r" % (sec.addr + p, s))
            p = e + 1

        print()
        print("=== short entries (<=6 chars) that look like format fragments ===")
        p = 0
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            try:
                s = blob[p:e].decode("utf-8")
            except Exception:
                s = None
            if s and 0 < len(s) <= 6 and re.search(r"%|gold|xp|exp|\+", s, re.I):
                print("   %#010x  %r" % (sec.addr + p, s))
            p = e + 1

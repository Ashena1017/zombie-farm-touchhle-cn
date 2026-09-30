"""Sweep __cstring (and every other section) in both slices for the same
mojibake signature the Localizable.strings files carry.

The strings file only accounts for '+200eE'.  '+1Ee' must come from a literal
inside the executable - and 'ZFSaleEndDateDay +%dĘę' at sub6 0x3d1c68 shows the
codex patch damaged those too.
"""
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"
BASE = ROOT / "zombie_farm_ipa/ZFR 1.0.zh-CN-unsigned.ipa"


def cstrings(sl):
    out = []
    for sec in sl.sections:
        if sec.name not in ("__cstring", "__objc_methname", "__ustring"):
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        p = 0
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            if e > p:
                raw = blob[p:e]
                try:
                    out.append((sec.addr + p, sec.name, raw.decode("utf-8")))
                except Exception:
                    pass
            p = e + 1
    return out


for ipa, tag in ((IPA, "current"), (BASE, "baseline")):
    with zipfile.ZipFile(ipa) as z:
        fat = z.read("Payload/ZFR.app/ZFR")
    print("=" * 78)
    print("%s  (%s)" % (tag, ipa.name))
    print("=" * 78)
    for sub in (6, 9):
        sl = next(s for s in parse_fat(fat) if s.subtype == sub)
        hits = []
        for addr, sec, s in cstrings(sl):
            if any(0x0100 <= ord(c) <= 0x024F for c in s):
                hits.append((addr, sec, s))
        print("  sub%d: %d string(s) with Latin Extended-A" % (sub, len(hits)))
        for addr, sec, s in hits:
            odd = ", ".join("%r U+%04X" % (c, ord(c)) for c in
                            sorted({c for c in s if 0x0100 <= ord(c) <= 0x024F}))
            print("     %#010x %-16s %r" % (addr, sec, s))
            print("         %s" % odd)

"""Full mojibake sweep of the CURRENT zh-Hans / zh-Hant Localizable.strings.

Two signatures were produced by the codex patch ladder:
  A) Latin Extended-A (U+0100..U+024F) - e.g. '+%i金子' -> '+%iėĚ'
  B) the classic UTF-8-read-as-CP1252 soup - e.g. '...ÁªèÈ™å'
Both show up in KEYS as well as VALUES, so scan both.
"""
import plistlib
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"

CJK = lambda s: any(0x2E80 <= ord(c) <= 0x9FFF or 0xF900 <= ord(c) <= 0xFAFF or
                    0xFF00 <= ord(c) <= 0xFFEF for c in s)
EXT_A = lambda s: any(0x0100 <= ord(c) <= 0x024F for c in s)
# CP1252-printable range that only shows up when UTF-8 bytes were misread
SOUP = lambda s: any(0x00A0 <= ord(c) <= 0x00FF or 0x2000 <= ord(c) <= 0x2122 for c in s)


def scan(name, table):
    print("=" * 78)
    print("%s  (%d keys)" % (name, len(table)))
    print("=" * 78)
    hits = []
    for k, v in table.items():
        if not isinstance(v, str):
            continue
        for label, s in (("KEY", k), ("VAL", v)):
            if EXT_A(s) or (SOUP(s) and not CJK(s) and any(c.isascii() and c.isalpha() for c in s)):
                hits.append((k, v, label))
                break
    for k, v, label in sorted(hits, key=lambda x: x[0]):
        where = "key" if label == "KEY" else "val"
        bad = sorted({c for c in (k if label == "KEY" else v)
                      if 0x00A0 <= ord(c) <= 0x024F or 0x2000 <= ord(c) <= 0x2122})
        ##########
        print("   [%s] %-40r" % (where, k))
        print("         -> %r" % v)
        print("         odd chars: %s" % ", ".join(
            "%r U+%04X %s" % (c, ord(c), unicodedata.name(c, "?")) for c in bad))
    print("   -> %d suspicious entr(ies)" % len(hits))
    print()
    return hits


with zipfile.ZipFile(IPA) as z:
    total = 0
    for lp in ("zh-Hans", "zh-Hant"):
        table = plistlib.loads(z.read("Payload/ZFR.app/%s.lproj/Localizable.strings" % lp))
        total += len(scan(lp, table))
    print("TOTAL: %d" % total)

"""Find every corrupted value in zh-Hans Localizable.strings.

The floating-text bug is a mojibake value:  '+%ig' -> '+%iėĚ'  (should be '+%i金币').
'ė' (U+0117) and 'Ě' (U+011B) are Latin Extended-A, which a CJK font renders as
plain e / E - exactly the "+200eE" the user photographed.  So: scan for every
value containing characters from that block (or other non-CJK oddities).
"""
import plistlib
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"
z = zipfile.ZipFile(IPA)
pl = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
en = plistlib.loads(z.read("Payload/ZFR.app/English.lproj/Localizable.strings"))

print("=" * 78)
print("A) values containing Latin Extended-A / Extended-B (U+0100..U+024F)")
print("=" * 78)
n = 0
for k, v in sorted(pl.items()):
    if not isinstance(v, str):
        continue
    bad = [c for c in v if 0x0100 <= ord(c) <= 0x024F]
    if bad:
        n += 1
        print("   key %-40r" % k)
        print("        zh = %-34r   <-- has %s" % (v, ", ".join(
            "%r U+%04X %s" % (c, ord(c), unicodedata.name(c, "?")) for c in set(bad))))
        print("        en = %r" % en.get(k, "<MISSING>"))
print("   -> %d value(s)" % n)

print()
print("=" * 78)
print("B) format-ish keys whose zh value is not what the key implies")
print("=" * 78)
for k in sorted(pl):
    if "%" in k:
        v = pl[k]
        if not isinstance(v, str):
            continue
        # count conversion specifiers on both sides
        def specs(s):
            return re.findall(r"%[-+ #0-9.]*[diufFeEgGxXocs@%]", s)
        if specs(k) != specs(v):
            print("   %-40r -> %r" % (k, v))
            print("        key specs=%s   value specs=%s" % (specs(k), specs(v)))

print()
print("=" * 78)
print("C) keys/values about the counted storage label (issue #3)")
print("=" * 78)
for k, v in sorted(pl.items()):
    if not isinstance(v, str):
        continue
    if re.search(r"%[di@][^A-Za-z]?\(|\(%|%\w*\s*\(|x\s*%|%i\b.*\(|Insta", k + v):
        print("   %-46r -> %r" % (k, v))

print()
print("=" * 78)
print("D) every key whose English value is exactly an item name we care about")
print("=" * 78)
for name in ("Insta-Grow", "Invasion Voucher", "Insta-Harvest", "Instant Plow",
             "Instant Harvest", "Insta-Plow"):
    print("   %-20s en=%r  zh=%r" % (name, en.get(name, "<MISSING>"), pl.get(name, "<MISSING>")))
print()
print("   keys mentioning 'Insta' or 'Instant':")
for k in sorted(pl):
    if "insta" in k.lower():
        print("      %-46r -> %r" % (k, pl[k]))

"""Batch 2 - localisation reconnaissance.

  #1  "Invasion Voucher"   (bottom info bar)
  #3  "Insta-Grow"
  #5  "+200eE" / "+1Ee"  floating text
"""
import plistlib
import re
import sys
import zipfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"
z = zipfile.ZipFile(IPA)

TERMS = ["Invasion Voucher", "Insta-Grow", "InstaGrow", "Insta Grow",
         "Gold", "Experience", "EXP", "eE", "Quick Grow", "Instant"]

print("=" * 72)
print("1) zh-Hans Localizable.strings entries")
print("=" * 72)
pl = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
for k, v in sorted(pl.items()):
    if any(t.lower() in k.lower() for t in TERMS):
        print("   %-44r -> %r" % (k, v))

print()
print("=" * 72)
print("2) values that contain 'eE' (the floating-text bug)")
print("=" * 72)
for k, v in sorted(pl.items()):
    if isinstance(v, str) and "eE" in v:
        print("   %-44r -> %r" % (k, v))

print()
print("=" * 72)
print("3) raw byte search in the executable")
print("=" * 72)
fat = z.read("Payload/ZFR.app/ZFR")
for t in ["Invasion Voucher", "Insta-Grow", "InstaGrow", "eE", "+%@", "金币", "经验"]:
    print("   %-22s %d" % (t, fat.count(t.encode("utf-8"))))

print()
print("=" * 72)
print("4) __cstring entries around the interesting words (sub6)")
print("=" * 72)
sl = next(s for s in parse_fat(fat) if s.subtype == 6)
for sec in sl.sections:
    if sec.name != "__cstring":
        continue
    blob = sl.data[sec.offset:sec.offset + sec.size]
    for pat in (rb"Invasion Voucher", rb"Insta-Grow", rb"[^ \x00]{0,6}eE[^ \x00]{0,6}"):
        for m in re.finditer(pat, blob):
            s = m.group().decode("latin1")
            if pat == rb"[^ \x00]{0,6}eE[^ \x00]{0,6}" and not re.search(r"\beE\b|eE$|^eE", s):
                continue
            print("   %-10s %-30r  @ %#x" % (sec.name, s, sec.addr + m.start()))

print()
print("=" * 72)
print("5) plists mentioning Insta-Grow / Invasion Voucher")
print("=" * 72)
for n in sorted(z.namelist()):
    if not n.lower().endswith((".plist", ".strings")) or "CodeSignature" in n:
        continue
    try:
        d = z.read(n)
    except Exception:
        continue
    for t in (b"Insta-Grow", b"Invasion Voucher"):
        if t in d:
            print("   %-58s %s" % (n.rsplit("/", 1)[-1], t.decode()))

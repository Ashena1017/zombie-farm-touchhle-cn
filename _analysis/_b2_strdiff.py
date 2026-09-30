"""Diff zh-Hans Localizable.strings between the untouched baseline and the
current build - the codex patch ladder silently corrupted some Chinese values
('+%ig' -> '+%iėĚ' instead of '+%i金子').  Find every other casualty.
"""
import plistlib
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
Z = ROOT / "zombie_farm_ipa"
BASE = Z / "ZFR 1.0.zh-CN-unsigned.ipa"
CUR = Z / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"


def load(ipa, lproj):
    with zipfile.ZipFile(ipa) as z:
        raw = z.read("Payload/ZFR.app/%s.lproj/Localizable.strings" % lproj)
    return plistlib.loads(raw), raw


for lproj in ("zh-Hans", "zh-Hant"):
    print("=" * 78)
    print("lproj = %s" % lproj)
    print("=" * 78)
    try:
        a, raw_a = load(BASE, lproj)
        b, raw_b = load(CUR, lproj)
    except KeyError as e:
        print("   missing: %s" % e)
        continue
    print("   baseline %d keys / %d bytes ; current %d keys / %d bytes"
          % (len(a), len(raw_a), len(b), len(raw_b)))
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    if only_a:
        print("   keys only in baseline (%d): %s" % (len(only_a), only_a[:10]))
    if only_b:
        print("   keys only in current (%d): %s" % (len(only_b), only_b[:10]))
    diffs = [(k, a[k], b[k]) for k in sorted(set(a) & set(b)) if a[k] != b[k]]
    print("   changed values: %d" % len(diffs))
    for k, va, vb in diffs:
        flag = ""
        if isinstance(vb, str) and any(0x0100 <= ord(c) <= 0x024F for c in vb):
            flag = "   <-- LATIN-EXT-A (mojibake)"
        elif isinstance(va, str) and isinstance(vb, str) and \
                any(ord(c) > 0x2E80 for c in va) and not any(ord(c) > 0x2E80 for c in vb):
            flag = "   <-- lost its Chinese!"
        print("      key %-34r" % k)
        print("         was %r" % va)
        print("         now %r%s" % (vb, flag))
        if flag:
            print("         units: was %d, now %d" % (len(va), len(vb)))

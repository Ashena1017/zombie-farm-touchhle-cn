#!/usr/bin/env python3
"""Which exclamation mark does this game's Chinese localization use?

The English key is 'Fertilized by %@!'.  Restoring the '!' raises a choice:
ASCII '!' (U+0021) or fullwidth '！' (U+FF01).  Decide from the shipped
translations rather than taste, and re-check the size cost of each.

Read-only.
"""
from __future__ import annotations

import plistlib
import sys
import zipfile
import zlib
from collections import Counter
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from patch_zfr_alert_fonts import parse_zip_layout  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IPA = ROOT / "zombie_farm_ipa" / (
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa")
LOC = "Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"
TABLE = "Payload/ZFR.app/Arial-BoldMT.strings"
FERT = "Fertilized by %@!"


def openstep(tbl: dict, overrides: dict) -> bytes:
    lines = ["{"]
    for k in sorted(tbl):
        v = overrides.get(k, tbl[k])
        esc = "".join(
            ch if 0x20 <= ord(ch) < 0x7F and ch not in '"\\' else "\\U%04X" % ord(ch)
            for ch in v)
        ek = k.replace("\\", "\\\\").replace('"', '\\"')
        lines.append('  "%s" = "%s";' % (ek, esc))
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("ascii")


def best_deflate(data: bytes) -> int:
    best = None
    for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED,
                     zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE, zlib.Z_FIXED):
        for level in range(1, 10):
            for ml in (8, 9):
                co = zlib.compressobj(level, zlib.DEFLATED, -15, ml, strategy)
                n = len(co.compress(data) + co.flush())
                best = n if best is None else min(best, n)
    return best


def main() -> int:
    with zipfile.ZipFile(IPA) as z:
        loc = plistlib.loads(z.read(LOC))
        tbl = plistlib.loads(z.read(TABLE))
    raw = IPA.read_bytes()
    slot = next(r["csize"] for r in parse_zip_layout(raw)["records"]
                if r["name"] == TABLE)

    print("== punctuation in the shipped zh-Hans translations ==")
    vals = [v for v in loc.values() if isinstance(v, str)]
    zh = [v for v in vals if any("\u4e00" <= c <= "\u9fff" for c in v)]
    print("   %d values, %d containing CJK" % (len(vals), len(zh)))

    counts = {
        "ASCII !  (U+0021)": sum(v.count("!") for v in zh),
        "fullwidth ！(U+FF01)": sum(v.count("\uff01") for v in zh),
        "ASCII ?  (U+003F)": sum(v.count("?") for v in zh),
        "fullwidth ？(U+FF1F)": sum(v.count("\uff1f") for v in zh),
        "ASCII ,  (U+002C)": sum(v.count(",") for v in zh),
        "fullwidth ，(U+FF0C)": sum(v.count("\uff0c") for v in zh),
        "ASCII :  (U+003A)": sum(v.count(":") for v in zh),
        "fullwidth ：(U+FF1A)": sum(v.count("\uff1a") for v in zh),
    }
    for k, n in counts.items():
        print("   %-24s %d" % (k, n))

    print("\n== translations that DO end with an exclamation ==")
    shown = 0
    for k, v in loc.items():
        if isinstance(v, str) and ("!" in v or "\uff01" in v):
            print("   %-34s %r" % (k[:34], v))
            shown += 1
            if shown >= 12:
                break
    if not shown:
        print("   (none)")

    print("\n== size cost of each choice (slot = %d) ==" % slot)
    for text, why in ((" %@施肥啦", "no exclamation"),
                      (" %@施肥啦!", "ASCII !"),
                      (" %@施肥啦！", "fullwidth ！"),
                      (" %@施肥了!", "faithful + ASCII !"),
                      (" %@施肥了！", "faithful + fullwidth ！")):
        n = best_deflate(openstep(tbl, {FERT: text}))
        print("   %-12s raw-text=%3d deflate=%3d  %s  (%s)"
              % (repr(text), len(openstep(tbl, {FERT: text})), n,
                 "FITS, %d spare" % (slot - n) if n <= slot
                 else "over by %d" % (n - slot), why))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

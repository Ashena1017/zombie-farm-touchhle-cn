#!/usr/bin/env python3
"""Size check for the candidate fertilize wordings, including the user's '啦'.

The user wants ' %@施肥啦' (leading space restored, 了 -> 啦).  Before building
anything, confirm it compresses into the same 189-byte slot as an OpenStep table.

Read-only.
"""
from __future__ import annotations

import plistlib
import sys
import zipfile
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from patch_zfr_alert_fonts import parse_zip_layout  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IPA = ROOT / "zombie_farm_ipa" / (
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa")
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
        cur = plistlib.loads(z.read(TABLE))
    raw = IPA.read_bytes()
    rec = next(r for r in parse_zip_layout(raw)["records"] if r["name"] == TABLE)
    slot = int(rec["csize"])
    print("slot = %d bytes (compressed)\n" % slot)

    cands = [
        ("%@施肥", "SHIPPED today (v19 compromise)"),
        (" %@施肥啦", "USER REQUEST: space + 啦"),
        (" %@施肥了", "faithful original"),
        ("%@施肥啦", "啦 without the leading space"),
        (" %@施肥啦!", "啦 + ascii !"),
        (" %@施肥啦！", "啦 + fullwidth ！"),
        (" %@施肥喽", "喽 variant"),
        (" %@施肥咯", "咯 variant"),
    ]
    print("== OpenStep + \\U escapes ==")
    for text, why in cands:
        data = openstep(cur, {FERT: text})
        n = best_deflate(data)
        mark = "FITS " if n <= slot else "over%d" % (n - slot)
        print("   %-12s units=%d raw=%3d best=%3d %s  %s"
              % (repr(text), len(text), len(data), n, mark, why))

    print("\n== bplist, for reference ==")
    for text, why in cands:
        data = plistlib.dumps({**cur, FERT: text}, fmt=plistlib.FMT_BINARY,
                              sort_keys=True)
        n = best_deflate(data)
        mark = "FITS " if n <= slot else "over%d" % (n - slot)
        print("   %-12s raw=%3d best=%3d %s" % (repr(text), len(data), n, mark))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

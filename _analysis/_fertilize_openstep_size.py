#!/usr/bin/env python3
"""Measure the OpenStep-with-\\U-escapes serialisation against the 189-byte slot.

Confirmed so far:
  * the game's loader (plist 1.8.0 `Value::from_reader`) falls back to an
    OpenStep/ASCII reader for non-binary, non-XML input;
  * the BRACED OpenStep form parses; the bare `"k" = "v";` list does not;
  * raw UTF-8 bytes arrive as Latin-1 mojibake, but `\\Uxxxx` escapes decode to
    the correct Chinese.

So an OpenStep table is a viable third format.  Question: does it fit the slot
WITH the faithful ' %@施肥了' intact?

Read-only.
"""
from __future__ import annotations

import plistlib
import struct
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
SLOT = 189


def openstep(tbl: dict, fertilize: str) -> bytes:
    """Braced OpenStep plist with \\Uxxxx escapes for non-ASCII."""
    lines = ["{"]
    for k in sorted(tbl):
        v = fertilize if k == FERT else tbl[k]
        esc = "".join(
            ch if 0x20 <= ord(ch) < 0x7F and ch not in '"\\' else "\\U%04X" % ord(ch)
            for ch in v)
        ek = k.replace("\\", "\\\\").replace('"', '\\"')
        lines.append('  "%s" = "%s";' % (ek, esc))
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("ascii")


def best_deflate(data: bytes) -> tuple[int, str]:
    best, who = None, ""
    for strategy, name in ((zlib.Z_DEFAULT_STRATEGY, "default"),
                           (zlib.Z_FILTERED, "filtered"),
                           (zlib.Z_HUFFMAN_ONLY, "huffman"),
                           (zlib.Z_RLE, "rle"),
                           (zlib.Z_FIXED, "fixed")):
        for level in range(1, 10):
            for ml in (8, 9):
                co = zlib.compressobj(level, zlib.DEFLATED, -15, ml, strategy)
                n = len(co.compress(data) + co.flush())
                if best is None or n < best:
                    best, who = n, "%s/L%d/M%d" % (name, level, ml)
    return best, who


def main() -> int:
    with zipfile.ZipFile(IPA) as z:
        cur = plistlib.loads(z.read(TABLE))
        raw = IPA.read_bytes()
    rec = next(r for r in parse_zip_layout(raw)["records"] if r["name"] == TABLE)
    slot = int(rec["csize"])
    print("== slot ==")
    print("   %s csize=%d" % (TABLE, slot))

    print("\n== formats, with the FAITHFUL text ' %@施肥了' ==")
    rows = []
    for label, data in (
        ("bplist (shipped format)", plistlib.dumps(
            {**cur, FERT: " %@施肥了"}, fmt=plistlib.FMT_BINARY, sort_keys=True)),
        ("XML plist", plistlib.dumps(
            {**cur, FERT: " %@施肥了"}, fmt=plistlib.FMT_XML, sort_keys=True)),
        ("OpenStep + \\U escapes", openstep(cur, " %@施肥了")),
    ):
        n, who = best_deflate(data)
        rows.append((label, len(data), n, who))
        print("   %-26s raw=%4d  best deflate=%3d (%s)  %s"
              % (label, len(data), n, who,
                 "FITS" if n <= slot else "over by %d" % (n - slot)))

    print("\n== the same, for comparison, with the SHIPPED text ==")
    for label, data in (
        ("bplist", plistlib.dumps(cur, fmt=plistlib.FMT_BINARY, sort_keys=True)),
        ("OpenStep + \\U escapes", openstep(cur, cur[FERT])),
    ):
        n, who = best_deflate(data)
        print("   %-26s raw=%4d  best deflate=%3d  %s"
              % (label, len(data), n, "FITS" if n <= slot else "over"))

    print("\n== verdict ==")
    os_faithful = [r for r in rows if r[0].startswith("OpenStep")][0]
    if os_faithful[2] <= slot:
        print("   The OpenStep form with the FAITHFUL text fits: %d <= %d"
              % (os_faithful[2], slot))
        print("   => v19's shortening was avoidable; it was a FORMAT choice, not a")
        print("      hard limit of the slot.")
    else:
        print("   Even OpenStep does not fit; the shortening was necessary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

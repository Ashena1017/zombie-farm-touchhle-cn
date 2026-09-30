#!/usr/bin/env python3
"""Is the 189-byte slot for Arial-BoldMT.strings really immovable?

The v19 note says the faithful text needs 193 compressed bytes but the member's
DEFLATE slot is 189, so two code units were dropped.  Before accepting that, check
whether the 4 missing bytes could come from anywhere:

  * slack/padding after the member's compressed data,
  * the gap before the next member,
  * a cheaper plist encoding (dedup, key order, alternate strategies),
  * re-compressing the member as STORED (no compression at all).

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
FAITHFUL = " %@施肥了"


def bplist(tbl: dict, sort: bool = True) -> bytes:
    return plistlib.dumps(tbl, fmt=plistlib.FMT_BINARY, sort_keys=sort)


def deflate_sizes(data: bytes) -> dict:
    out = {}
    for strategy, name in ((zlib.Z_DEFAULT_STRATEGY, "default"),
                           (zlib.Z_FILTERED, "filtered"),
                           (zlib.Z_HUFFMAN_ONLY, "huffman"),
                           (zlib.Z_RLE, "rle"),
                           (zlib.Z_FIXED, "fixed")):
        for level in range(1, 10):
            co = zlib.compressobj(level, zlib.DEFLATED, -15, 9, strategy)
            n = len(co.compress(data) + co.flush())
            out["%s/L%d" % (name, level)] = n
    return out


def main() -> int:
    raw = IPA.read_bytes()
    layout = parse_zip_layout(raw)
    recs = layout["records"]
    idx = next(i for i, r in enumerate(recs) if r["name"] == TABLE)
    r = recs[idx]
    print("== member ==")
    print("   name        %s" % r["name"])
    print("   local_off   %#x" % r["local_offset"])
    print("   offset      %#x (central dir)" % r["offset"])
    print("   csize       %d" % r["csize"])
    print("   usize       %d" % r["usize"])
    print("   flag        %#x   method %d" % (r["flag"], r["method"]))

    print("\n== what is physically adjacent? ==")
    local = int(r["local_offset"])
    (sig, need, flag, method, mt, md, crc, csize, usize,
     nlen, elen) = struct.unpack_from("<I5H3I2H", raw, local)
    data_start = local + 30 + nlen + elen
    data_end = data_start + csize
    print("   data %#x..%#x" % (data_start, data_end))
    nxt = recs[idx + 1]
    gap = int(nxt["local_offset"]) - data_end
    print("   next member  %s at %#x" % (nxt["name"], nxt["local_offset"]))
    print("   GAP between them = %d byte(s)" % gap)

    print("\n== local header extra field ==")
    print("   name_len=%d extra_len=%d" % (nlen, elen))
    if elen:
        print("   extra: %s" % raw[local + 30 + nlen:local + 30 + nlen + elen].hex())

    print("\n== is the compressed data exactly full? ==")
    stored = raw[data_start:data_end]
    plain = None
    try:
        d = zlib.decompressobj(-15)
        plain = d.decompress(stored)
        unused = d.unused_data
        print("   decompresses to %d bytes, unused tail = %d byte(s)"
              % (len(plain), len(unused)))
        if unused:
            print("   -> the member's stream ENDS EARLY; %d trailing byte(s) are"
                  " dead space inside the slot!" % len(unused))
        else:
            print("   -> the slot is exactly filled; no dead space to reclaim")
    except Exception as ex:
        print("   decompress failed: %s" % ex)
    if plain is None:
        return 1

    print("\n== plist encoding options for the FAITHFUL text ==")
    cur = plistlib.loads(plain)
    faithful = dict(cur)
    faithful[FERT] = FAITHFUL
    for sort in (True, False):
        b = bplist(faithful, sort=sort)
        sizes = deflate_sizes(b)
        best = min(sizes.values())
        print("   sort_keys=%-5s raw=%3d  best deflate=%3d (%s)"
              % (sort, len(b), best, min(sizes, key=sizes.get)))

    print("\n== how much dedup does plistlib already do? ==")
    b = bplist(faithful)
    vals = list(faithful.values())
    print("   %d values, %d distinct" % (len(vals), len(set(vals))))
    print("   raw size %d" % len(b))

    print("\n== STORED (uncompressed) option ==")
    print("   faithful raw plist = %d bytes" % len(bplist(faithful)))
    print("   shipped  raw plist = %d bytes" % len(bplist(cur)))
    print("   (a STORED member would need a slot >= its raw size; the slot is"
          " %d, so STORED is not viable either)" % csize)

    print("\n== every wording that fits, ranked by fidelity ==")
    cands = [
        (" %@施肥了", "faithful"),
        (" %@施肥！", "了 -> full-width !"),
        (" %@施肥!", "了 -> ascii !"),
        ("%@施肥了", "drop leading space"),
        (" %@施肥", "drop 了"),
        ("%@施肥", "drop both (SHIPPED)"),
    ]
    for text, why in cands:
        tbl = dict(cur)
        tbl[FERT] = text
        best = min(deflate_sizes(bplist(tbl)).values())
        print("   %-10s units=%d best=%3d %s  %s"
              % (repr(text), len(text), best,
                 "FITS " if best <= csize else "over%d" % (best - csize), why))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

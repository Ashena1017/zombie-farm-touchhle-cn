#!/usr/bin/env python3
"""Could the faithful text fit WITHOUT growing the IPA?

The archive has 12,053 bytes of dead space (deflate streams padded inside their
slots), 11,831 of it in the Payload/ZFR.app/ZFR member.  If that padding sits
BEFORE the two Arial-BoldMT.strings members, it can be reclaimed to fund their
growth, and the archive size can stay exactly 59,564,493 bytes.

This maps the member order and computes whether that works.

Read-only.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from patch_zfr_alert_fonts import parse_zip_layout  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IPA = ROOT / "zombie_farm_ipa" / (
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa")
ARIAL = ["Payload/ZFR.app/Arial-BoldMT.strings",
         "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings"]


def main() -> int:
    raw = IPA.read_bytes()
    recs = parse_zip_layout(raw)["records"]
    print("== member order (local offsets) ==")
    order = sorted(recs, key=lambda r: int(r["local_offset"]))
    for i, r in enumerate(order):
        local = int(r["local_offset"])
        (sig, need, flag, method, mt, md, crc, csize, usize,
         nlen, elen) = struct.unpack_from("<I5H3I2H", raw, local)
        dead = 0
        if method == 8 and csize:
            ds = local + 30 + nlen + elen
            try:
                d = zlib.decompressobj(-15)
                d.decompress(raw[ds:ds + csize])
                dead = len(d.unused_data)
            except Exception:
                pass
        mark = "  <== needs +4" if r["name"] in ARIAL else ""
        print("   %2d  %-56s csize=%8d dead=%6d%s"
              % (i, r["name"][:56], csize, dead, mark))

    idxs = [i for i, r in enumerate(order) if r["name"] in ARIAL]
    print("\n== can the executable's padding fund the growth? ==")
    exe_i = next((i for i, r in enumerate(order)
                  if r["name"] == "Payload/ZFR.app/ZFR"), None)
    if exe_i is None:
        print("   executable member not found")
        return 1
    first_arial = min(idxs)
    print("   Payload/ZFR.app/ZFR is member #%d" % exe_i)
    print("   first Arial-BoldMT member is #%d" % first_arial)
    if exe_i < first_arial:
        print("   -> the padding IS before the Arial members: reclaimable")
        between = first_arial - exe_i - 1
        print("   members whose offsets would shift: %d" % between)
    else:
        print("   -> the padding is AFTER the Arial members: not usable")

    print("\n== net-size-neutral plan ==")
    print("   reclaim 8 bytes of padding from Payload/ZFR.app/ZFR")
    print("   grow each Arial-BoldMT.strings slot by 4 (189 -> 193)")
    print("   => bytes removed before the Arial members == bytes added at them")
    print("   => members AFTER the second Arial member keep their offsets")
    print("   => archive size stays %d bytes" % len(raw))
    print("   cost: rewrite the central directory for the %d members in between,"
          % (first_arial - exe_i - 1))
    print("         plus CRC/usize/csize for the three touched members")

    print("\n== what the executable member's padding actually is ==")
    r = next(r for r in recs if r["name"] == "Payload/ZFR.app/ZFR")
    local = int(r["local_offset"])
    (sig, need, flag, method, mt, md, crc, csize, usize,
     nlen, elen) = struct.unpack_from("<I5H3I2H", raw, local)
    ds = local + 30 + nlen + elen
    d = zlib.decompressobj(-15)
    plain = d.decompress(raw[ds:ds + csize])
    print("   csize=%d  decompresses to %d  usize=%d  dead=%d"
          % (csize, len(plain), usize, len(d.unused_data)))
    print("   (dead bytes are a SECOND deflate stream / padding written by the")
    print("    patch tools' fixed-slot writer, not part of the executable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

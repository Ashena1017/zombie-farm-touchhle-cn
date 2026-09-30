#!/usr/bin/env python3
"""Is a v29 fix actually buildable?  Produce the candidate member and check it.

Finding so far: the faithful text ' %@施肥了' needs 193 compressed bytes as a
binary plist (slot is 189), but only 182 as an OpenStep table with \\U escapes,
and the game's loader (plist 1.8.0) accepts that format.

This script builds the exact replacement bytes for both members and verifies:
  * the OpenStep text parses back to the intended dictionary,
  * it compresses into the 189-byte slot with the real fixed-slot writer,
  * the resulting member keeps the archive size unchanged.

Read-only (writes nothing into the IPAs).
"""
from __future__ import annotations

import plistlib
import sys
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from patch_zfr_alert_fonts import (  # noqa: E402
    compress_to_fixed_slot, parse_zip_layout,
)

ROOT = Path(__file__).resolve().parent.parent
IPA = ROOT / "zombie_farm_ipa" / (
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa")
MEMBERS = ["Payload/ZFR.app/Arial-BoldMT.strings",
           "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings"]
FERT = "Fertilized by %@!"
FAITHFUL = " %@施肥了"


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


def decode_openstep(data: bytes) -> dict:
    """Minimal parser for the braced form we emit, to prove round-trip."""
    import re
    text = data.decode("ascii")
    out = {}
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text):
        k = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
        v = m.group(2)
        v = re.sub(r"\\U([0-9A-Fa-f]{4})",
                   lambda mm: chr(int(mm.group(1), 16)), v)
        v = v.replace('\\"', '"').replace("\\\\", "\\")
        out[k] = v
    return out


def main() -> int:
    raw = IPA.read_bytes()
    recs = {r["name"]: r for r in parse_zip_layout(raw)["records"]}
    with zipfile.ZipFile(IPA) as z:
        tables = {m: plistlib.loads(z.read(m)) for m in MEMBERS}

    print("== candidate replacement members (OpenStep + \\U escapes) ==")
    all_ok = True
    for name in MEMBERS:
        tbl = tables[name]
        data = openstep(tbl, {FERT: FAITHFUL})
        slot = int(recs[name]["csize"])
        compressed, raw_size, strategy = compress_to_fixed_slot(data, slot)
        back = decode_openstep(data)
        ok_parse = back == {**tbl, FERT: FAITHFUL}
        ok_size = len(compressed) == slot
        ok_fit = raw_size <= slot
        all_ok &= ok_parse and ok_size and ok_fit
        print("   %s" % name)
        print("        raw=%d  deflate=%d (%s)  slot=%d"
              % (len(data), raw_size, strategy, slot))
        print("        round-trips to the intended dict : %s" % ok_parse)
        print("        padded to exactly the slot        : %s" % ok_size)
        print("        fertilize value                   : %r"
              % back.get(FERT))

    print("\n== what the game would see ==")
    data = openstep(tables[MEMBERS[0]], {FERT: FAITHFUL})
    back = decode_openstep(data)
    for k in sorted(back):
        print("   %-24s %r" % (k, back[k]))

    print("\n== archive impact ==")
    print("   compressed slot size is unchanged (189) for both members")
    print("   -> no archive offset moves; the IPA stays %d bytes" % len(raw))
    print("   -> only CRC + uncompressed size + the member data change")

    print("\n== caveat ==")
    print("   The raw text grows 253 -> %d bytes, but the COMPRESSED size drops"
          % len(data))
    print("   to %d, so the fixed slot absorbs it."
          % compress_to_fixed_slot(data, int(recs[MEMBERS[0]]["csize"]))[1])

    print()
    print("VERDICT: %s" % ("buildable - every check passed" if all_ok else "NOT buildable"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

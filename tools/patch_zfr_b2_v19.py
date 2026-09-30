#!/usr/bin/env python3
"""v19fix - repair the last mojibake table: Arial-BoldMT.strings (the fertilize float).

THE BUG THE USER PHOTOGRAPHED
-----------------------------
Fertilizing a crop shows a floating label rendering as garbage instead of
Chinese.  It is NOT in Localizable.strings (v15 fixed those three values) and NOT
in the executable (v16/v17 fixed those ten CFStrings): it lives in a **separate
strings table named after the font**:

    Payload/ZFR.app/Arial-BoldMT.strings
    Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings

Neither member exists in the untouched baseline -- the codex patch CREATED them,
with eight mojibake values, and this was the one place never inspected:

    'Fertilized by %@!'    -> ' %@' + 3 mojibake chars   (should be ' %@施肥了')
    'Cupid Zombie'         -> 5 mojibake chars           (丘比特僵尸)
    'Flower Zombie'        -> 4                          (花花僵尸)
    'Garden Zombie'        -> 4                          (园丁僵尸)
    'Green Flower Zombie'  -> 4                          (花花僵尸)
    'ZomBotanist'          -> 4                          (生态僵尸)
    'Zombee'               -> 4                          (蜜蜂僵尸)
    'Zombutterfly'         -> 4                          (蝴蝶僵尸)

The correct text is not a guess: zh-Hans Localizable.strings already carries it
(the codex patch translated these keys there and corrupted them here).

THE ZIP SLOT PROBLEM
--------------------
Both members sit in a fixed 189-byte DEFLATE slot sized by the codex patch for
its own, highly compressible mojibake.  The faithful repair needs 193 bytes, and
nothing gets under that: every level 1..9 x 5 strategies x memLevel 8/9 x
wbits +/-15, every key ordering, and even a hand-written deduplicated bplist all
land on 193.  Shortening the fertilize message from ' %@施肥了' (6 code units) to
'%@施肥' (4) brings it to 188, which fits -- so that one string loses a leading
space and the particle, reading "<fertilizer>施肥" instead of " <fertilizer>施肥了".

Because that changes the length, the plist is re-serialised rather than patched
byte-for-byte, so `usize` must be rewritten in both the local header and the
central directory.  The compressed slot keeps its size, so no archive offset
moves and the IPA stays 59,564,493 bytes.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import plistlib
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_zfr_alert_fonts import (  # noqa: E402
    EXECUTABLE, compress_to_fixed_slot, parse_zip_layout, raw_deflate, sha256,
    write_exclusive,
)

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed-fonts-v18fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v19fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v19fix.report.json"

TABLE = "Arial-BoldMT.strings"
MEMBERS = ["Payload/ZFR.app/%s" % TABLE,
           "Payload/ZFR.app/zh-Hans.lproj/%s" % TABLE]
SOURCE_OF_TRUTH = "Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"

# The one string that gives up two code units so the member fits its ZIP slot.
FIT_OVERRIDES = {"Fertilized by %@!": "%@\u65bd\u80a5"}


def replace_member_resized(raw: bytes, name: str, data: bytes) -> tuple[bytes, dict[str, Any]]:
    """Fixed-slot surgery that ALSO updates the uncompressed size."""
    layout = parse_zip_layout(raw)
    record = next((r for r in layout["records"] if r["name"] == name), None)
    if record is None:
        raise ValueError("ZIP member %r not found" % name)
    if record["method"] != zipfile.ZIP_DEFLATED:
        raise ValueError("%s is not DEFLATE" % name)
    if record["flag"] & 0x08:
        raise ValueError("%s uses a data descriptor" % name)

    local = int(record["local_offset"])
    if raw[local:local + 4] != b"PK\x03\x04":
        raise ValueError("%s local header malformed" % name)
    (_sig, _need, _flag, _method, _mt, _md, local_crc, local_csize, local_usize,
     name_len, extra_len) = struct.unpack_from("<I5H3I2H", raw, local)
    if local_crc != record["crc"] or local_csize != record["csize"] or \
            local_usize != record["usize"]:
        raise ValueError("%s local/central size mismatch" % name)
    if raw[int(record["offset"]):int(record["offset"]) + 4] != b"PK\x01\x02":
        raise ValueError("%s central-directory entry malformed" % name)

    data_start = local + 30 + name_len + extra_len
    data_end = data_start + int(record["csize"])
    compressed, raw_size, strategy = compress_to_fixed_slot(data, int(record["csize"]))
    crc = zlib.crc32(data) & 0xFFFFFFFF
    out = bytearray(raw)
    out[data_start:data_end] = compressed
    struct.pack_into("<I", out, local + 14, crc)                # local crc32
    struct.pack_into("<I", out, local + 22, len(data))          # local usize
    struct.pack_into("<I", out, int(record["offset"]) + 16, crc)
    struct.pack_into("<I", out, int(record["offset"]) + 24, len(data))
    return bytes(out), {
        "member": name,
        "usize_before": int(record["usize"]),
        "usize_after": len(data),
        "slot": int(record["csize"]),
        "raw_deflate_size": raw_size,
        "padding_bytes": int(record["csize"]) - raw_size,
        "compression_strategy": strategy,
        "crc32": f"{crc:08x}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    ap.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    ap.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        members = {n: archive.read(n) for n in MEMBERS}
        truth = plistlib.loads(archive.read(SOURCE_OF_TRUTH))
        exe = archive.read(EXECUTABLE)
    slots = {r["name"]: int(r["csize"]) for r in parse_zip_layout(source)["records"]}

    ipa_patched = source
    reports: list[dict[str, Any]] = []
    finals: dict[str, dict[str, str]] = {}

    for name in MEMBERS:
        raw = members[name]
        table = plistlib.loads(raw)
        fixed: dict[str, str] = {}
        repairs = []
        for key, broken in table.items():
            correct = FIT_OVERRIDES.get(key, truth.get(key))
            if correct is None:
                raise ValueError("%s: no zh-Hans translation for %r" % (name, key))
            fixed[key] = correct
            if broken != correct:
                repairs.append({"key": key, "before": broken, "after": correct})
        new_raw = plistlib.dumps(fixed, fmt=plistlib.FMT_BINARY, sort_keys=True)
        if plistlib.loads(new_raw) != fixed:
            raise ValueError("%s: round-trip mismatch" % name)
        comp = raw_deflate(new_raw, 9, zlib.Z_DEFAULT_STRATEGY)
        if len(comp) > slots[name]:
            raise ValueError("%s: repaired member deflates to %d, slot is %d"
                             % (name, len(comp), slots[name]))
        print("  %s: %d repair(s);  raw %d -> %d, deflate %d <= slot %d"
              % (name, len(repairs), len(raw), len(new_raw), len(comp), slots[name]))

        ipa_patched, meta = replace_member_resized(ipa_patched, name, new_raw)
        meta["repairs"] = repairs
        reports.append(meta)
        finals[name] = fixed

    if len(ipa_patched) != len(source):
        raise ValueError("output archive changed size")

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "findings": {
            "table": "the codex patch created Arial-BoldMT.strings (and its zh-Hans "
                     "copy); no earlier build step ever rewrote it, so its eight "
                     "mojibake values survived v15/v16/v17",
            "symptom": "the floating label shown when a zombie fertilizes a crop",
            "slot": "the fixed DEFLATE slot is 189 bytes and the faithful repair "
                    "needs 193; only shortening the fertilize message to '%@施肥' "
                    "fits (188)",
        },
        "input": {"name": args.input.name, "size": len(source), "sha256": sha256(source)},
        "members": reports,
        "output": {"name": args.output.name, "size": len(ipa_patched),
                   "sha256": sha256(ipa_patched)},
    }

    if args.dry_run:
        report["dry_run"] = True
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    with zipfile.ZipFile(io.BytesIO(ipa_patched)) as archive:
        if archive.testzip() is not None:
            raise ValueError("output archive failed testzip()")
        for name in MEMBERS:
            got = plistlib.loads(archive.read(name))
            if got != finals[name]:
                raise ValueError("%s: readback mismatch" % name)
    write_exclusive(args.output, ipa_patched)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print("wrote %s  (%d bytes)" % (args.output.name, len(ipa_patched)))
    print("  ipa sha256 = %s" % report["output"]["sha256"])
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

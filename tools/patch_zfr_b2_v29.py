#!/usr/bin/env python3
"""v29fix - restore the fertilize float's lost leading space and particle.

THE PROBLEM
-----------
`Fertilized by %@!` (shown when a zombie fertilizes a crop) should read
' %@施肥了'.  v19fix repaired the codex mojibake in this table but shortened the
value to '%@施肥', dropping a leading space and the particle, because the member
sits in a fixed 189-byte DEFLATE slot and the faithful text needs 193 bytes **as
a binary plist**.

THE CORRECTION
--------------
189 bytes was never a hard limit - it was a FORMAT limit.  `.strings` members may
also be OpenStep property lists (`{ "key" = "value"; }` with \\Uxxxx escapes for
non-ASCII), which compress far better:

    bplist,  ' %@施肥啦'  -> 193 bytes   (over the slot)
    OpenStep,' %@施肥啦'  -> 182 bytes   (fits, 7 bytes spare)

The game can read it: the table is loaded through
-[NSBundle localizedStringForKey:value:table:] ->
[NSDictionary dictionaryWithContentsOfURL:] -> deserialize_plist_from_file ->
`plist::Value::from_reader`, and the plist crate's Reader auto-detects the
encoding (binary magic -> binary, else XML, else the OpenStep/ASCII reader).
Verified by compiling a probe against the same crate version (1.8.0): the braced
OpenStep form with \\U escapes parses and yields the correct Chinese.

Two format traps, both confirmed by that probe:
  * the enclosing braces are REQUIRED - a bare `"k" = "v";` list is rejected
    with `ExpectedEndOfEventStream`;
  * raw UTF-8 bytes must NOT be written directly - the ASCII reader maps bytes
    1:1, so Chinese turns into Latin-1 mojibake.  Use \\Uxxxx escapes.

WHAT THIS PATCH CHANGES
-----------------------
Both copies of the table are re-serialised as OpenStep with the requested wording:

    'Fertilized by %@!'  ->  ' %@施肥啦！'

'啦！' rather than the original '了': the user asked for 啦, and the game's own
zh-Hans localization prefers fullwidth ！ over ASCII ! (500 vs 67 occurrences in
CJK values) and already uses the exact 啦！ pair for 'ZOMBIE FARM GOES SOCIAL!'
('僵尸农场更新到社交版啦！').  That wording costs 186 of the 189 bytes.

The other seven values are carried over unchanged.  Because the compressed slot
keeps its exact size, no archive offset moves and the IPA stays 59,564,493 bytes;
only the two members' CRC, uncompressed size and data change.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import plistlib
import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_zfr_alert_fonts import (  # noqa: E402
    compress_to_fixed_slot, outside_ranges_equal, parse_zip_layout, sha256,
    write_exclusive,
)

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed-fonts-v28fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v29fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v29fix.report.json"

INPUT_ZIP_SHA256 = "7B37DC7CF874D478BA25D458871B2D19F1B58532E83223C52A5C9519B5BDA7F8"

TABLE = "Arial-BoldMT.strings"
MEMBERS = [f"Payload/ZFR.app/{TABLE}",
           f"Payload/ZFR.app/zh-Hans.lproj/{TABLE}"]
FERT_KEY = "Fertilized by %@!"
# '啦' + fullwidth '！' rather than the original '了':
#   * the user asked for 啦 (the key ends in '!', so a more exclamatory particle
#     suits it);
#   * the game's own zh-Hans localization uses fullwidth ！ far more often than
#     ASCII ! (500 vs 67 occurrences in CJK values), and it already contains the
#     exact 啦！ combination: 'ZOMBIE FARM GOES SOCIAL!' ->
#     '僵尸农场更新到社交版啦！'
FERT_VALUE = " %@施肥啦！"

# Every value must match what v28fix already ships, so this patch cannot silently
# change a string that some earlier round got right.
EXPECTED_VALUES = {
    "Cupid Zombie": "丘比特僵尸",
    "Fertilized by %@!": "%@施肥",          # repaired by this patch
    "Flower Zombie": "花花僵尸",
    "Garden Zombie": "园丁僵尸",
    "Green Flower Zombie": "花花僵尸",
    "ZomBotanist": "生态僵尸",
    "Zombee": "蜜蜂僵尸",
    "Zombutterfly": "蝴蝶僵尸",
}


# ------------------------------------------------------------------ serialiser
def escape_openstep(value: str) -> str:
    """OpenStep string body: printable ASCII verbatim, everything else \\Uxxxx."""
    out = []
    for ch in value:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif 0x20 <= o < 0x7F:
            out.append(ch)
        elif o > 0xFFFF:
            # Surrogate pair, as OpenStep \\U escapes are UTF-16 code units.
            o -= 0x10000
            out.append("\\U%04X\\U%04X" % (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)))
        else:
            out.append("\\U%04X" % o)
    return "".join(out)


def to_openstep(table: dict[str, str]) -> bytes:
    """Braced OpenStep plist (the form the plist crate's ASCII reader accepts)."""
    lines = ["{"]
    for key in sorted(table):
        lines.append('  "%s" = "%s";' % (escape_openstep(key),
                                         escape_openstep(table[key])))
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("ascii")


def parse_openstep(data: bytes) -> dict[str, str]:
    """Decode the braced form we emit, for an independent round-trip check."""
    text = data.decode("ascii")
    out: dict[str, str] = {}
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text):
        key = unescape_openstep(m.group(1))
        out[key] = unescape_openstep(m.group(2))
    return out


def unescape_openstep(body: str) -> str:
    def repl(m: re.Match) -> str:
        return chr(int(m.group(1), 16))
    s = re.sub(r"\\U([0-9A-Fa-f]{4})", repl, body)
    return s.replace('\\"', '"').replace("\\\\", "\\")


# ------------------------------------------------------------------ slot writer
def replace_member_resized(raw: bytes, name: str, data: bytes) -> tuple[bytes, dict[str, Any]]:
    """Fixed-slot surgery that also updates the uncompressed size and CRC."""
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
    struct.pack_into("<I", out, local + 14, crc)                 # local crc32
    struct.pack_into("<I", out, local + 22, len(data))           # local usize
    struct.pack_into("<I", out, int(record["offset"]) + 16, crc)
    struct.pack_into("<I", out, int(record["offset"]) + 24, len(data))
    return bytes(out), {
        "member": name,
        "format_before": "binary plist",
        "format_after": "OpenStep text",
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
    got_zip = sha256(source).upper()
    if got_zip != INPUT_ZIP_SHA256:
        raise ValueError(f"unexpected input archive sha256 {got_zip}")

    with zipfile.ZipFile(args.input) as archive:
        members = {n: archive.read(n) for n in MEMBERS}
        exe = archive.read("Payload/ZFR.app/ZFR")
    slots = {r["name"]: int(r["csize"]) for r in parse_zip_layout(source)["records"]}

    # ---- the input tables must be exactly what v28fix ships -----------------
    for name in MEMBERS:
        table = plistlib.loads(members[name])
        if table != EXPECTED_VALUES:
            raise ValueError(
                "%s does not match the v28fix values:\n  got      %r\n  expected %r"
                % (name, table, EXPECTED_VALUES))

    # ---- build the replacements -------------------------------------------
    target = dict(EXPECTED_VALUES)
    target[FERT_KEY] = FERT_VALUE
    new_raw = to_openstep(target)

    # independent round-trip through our own decoder
    back = parse_openstep(new_raw)
    if back != target:
        raise ValueError("OpenStep round-trip mismatch: %r" % back)
    if back[FERT_KEY] != FERT_VALUE:
        raise ValueError("fertilize value did not survive: %r" % back[FERT_KEY])

    # format traps that the probe exposed, asserted so a future edit cannot
    # silently reintroduce them
    if not new_raw.startswith(b"{") or not new_raw.rstrip().endswith(b"}"):
        raise ValueError("OpenStep output must be brace-delimited")
    if any(b > 0x7F for b in new_raw):
        raise ValueError("OpenStep output must be pure ASCII (use \\U escapes)")
    if FERT_VALUE.encode("utf-8") in new_raw:
        raise ValueError("raw UTF-8 leaked into the OpenStep text")

    ipa_patched = source
    reports: list[dict[str, Any]] = []
    for name in MEMBERS:
        ipa_patched, meta = replace_member_resized(ipa_patched, name, new_raw)
        reports.append(meta)

    if len(ipa_patched) != len(source):
        raise ValueError("output archive changed size")

    # ---- readback ----------------------------------------------------------
    with zipfile.ZipFile(io.BytesIO(ipa_patched)) as archive:
        if archive.testzip() is not None:
            raise ValueError("output archive failed testzip()")
        for name in MEMBERS:
            stored = archive.read(name)
            if stored != new_raw:
                raise ValueError("%s: readback differs" % name)
            if parse_openstep(stored) != target:
                raise ValueError("%s: readback does not decode to the target" % name)
        if archive.read("Payload/ZFR.app/ZFR") != exe:
            raise ValueError("the executable changed")
        names_before = [i.filename for i in zipfile.ZipFile(args.input).infolist()]
        names_after = [i.filename for i in archive.infolist()]
        if names_before != names_after:
            raise ValueError("the member list changed")

    # ---- only the two members' bytes differ --------------------------------
    # Three things change per member: the CRC and uncompressed size in the LOCAL
    # header, the member's compressed data, and the same two fields in the
    # CENTRAL DIRECTORY entry.  Declare all of them, so the equality check below
    # actually proves nothing else moved.
    diff_ranges = []
    for r in parse_zip_layout(source)["records"]:
        if r["name"] not in MEMBERS:
            continue
        local = int(r["local_offset"])
        (sig, need, flag, method, mt, md, crc, csize, usize,
         nlen, elen) = struct.unpack_from("<I5H3I2H", source, local)
        # local header: crc(14) csize(18) usize(22) .. through the data
        diff_ranges.append((local + 14, local + 30 + nlen + elen + csize))
        # central directory: crc(16) csize(20) usize(24) .. name/extra/comment
        central = int(r["offset"])
        diff_ranges.append((central + 16, central + 28))
    diff_ranges.sort()
    for lo, hi in diff_ranges:
        if source[lo:hi] == ipa_patched[lo:hi]:
            raise ValueError("declared change range %#x..%#x is identical" % (lo, hi))
    if not outside_ranges_equal(source, ipa_patched, [list(r) for r in diff_ranges]):
        raise ValueError("bytes changed outside the two members")

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "supersedes": "fixed-fonts-v28fix.ipa",
        "problem": "v19fix shortened 'Fertilized by %@!' from ' %@施肥了' to "
                   "'%@施肥' because the faithful text needs 193 compressed bytes "
                   "and the member's DEFLATE slot is 189.",
        "correction": "189 bytes was a FORMAT limit, not a hard limit.  v19fix "
                      "only tried binary plists; an OpenStep property list with "
                      "\\Uxxxx escapes compresses the same content to 182 bytes.",
        "loader_evidence": "-[NSBundle localizedStringForKey:value:table:] -> "
                           "[NSDictionary dictionaryWithContentsOfURL:] -> "
                           "deserialize_plist_from_file -> plist::Value::from_reader; "
                           "the plist 1.8.0 Reader auto-detects binary/XML/OpenStep. "
                           "Confirmed with a probe compiled against the same crate: "
                           "braced OpenStep + \\U escapes parses to the right Chinese; "
                           "a bare unbraced list is rejected; raw UTF-8 becomes "
                           "Latin-1 mojibake.",
        "value": {"key": FERT_KEY, "before": EXPECTED_VALUES[FERT_KEY],
                  "after": FERT_VALUE},
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source),
                  "executable_sha256": sha256(exe)},
        "members": reports,
        "member_count": len(reports),
        "other_values_unchanged": {k: v for k, v in EXPECTED_VALUES.items()
                                   if k != FERT_KEY},
    }

    if args.dry_run:
        report["dry_run"] = True
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    write_exclusive(args.output, ipa_patched)
    report["output"] = {"name": args.output.name, "size": len(ipa_patched),
                        "sha256": sha256(ipa_patched),
                        "executable_sha256": sha256(exe)}
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")

    print("wrote %s  (%d bytes)" % (args.output.name, len(ipa_patched)))
    print("  ipa sha256 = %s" % report["output"]["sha256"])
    for m in reports:
        print("  %s" % m["member"])
        print("      %s -> %s   usize %d -> %d   deflate %d <= slot %d (%s)"
              % (m["format_before"], m["format_after"], m["usize_before"],
                 m["usize_after"], m["raw_deflate_size"], m["slot"],
                 m["compression_strategy"]))
    print("  %r -> %r" % (EXPECTED_VALUES[FERT_KEY], FERT_VALUE))
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

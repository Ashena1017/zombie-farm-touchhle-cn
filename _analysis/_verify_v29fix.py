#!/usr/bin/env python3
"""Independent verifier for v29fix.

Deliberately does NOT import the v29 patcher: everything is re-derived from the
two IPA files, so a bug in the patcher cannot make its own verification pass.

Proves:
 1. archive: same size, testzip clean, same member list, FAT/executable untouched
 2. exactly two members changed, and only in their local header + data + central
    directory entry
 3. the new members are OpenStep text (braced, pure ASCII, \\U escapes) and decode
    to the intended dictionary - including ' %@施肥啦！' for the fertilize key
 4. the other seven values are byte-for-byte the same strings as v28fix
 5. both members still fit their original 189-byte compressed slot, and the slot
    size itself is unchanged
 6. the executable and every other member are byte-identical to v28fix
"""
import hashlib
import plistlib
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent,
                        *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from patch_zfr_alert_fonts import parse_zip_layout  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v28fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v29fix.ipa"
EXE = "Payload/ZFR.app/ZFR"
TABLE = "Arial-BoldMT.strings"
MEMBERS = [f"Payload/ZFR.app/{TABLE}",
           f"Payload/ZFR.app/zh-Hans.lproj/{TABLE}"]
FERT = "Fertilized by %@!"
FERT_WANT = " %@施肥啦！"
V28_SHA = "7B37DC7CF874D478BA25D458871B2D19F1B58532E83223C52A5C9519B5BDA7F8"
FAIL = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def unescape(body: str) -> str:
    s = re.sub(r"\\U([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), body)
    return s.replace('\\"', '"').replace("\\\\", "\\")


def parse_openstep(data: bytes) -> dict:
    text = data.decode("ascii")
    return {unescape(m.group(1)): unescape(m.group(2))
            for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;',
                                 text)}


old_raw, new_raw = OLD.read_bytes(), NEW.read_bytes()
with zipfile.ZipFile(OLD) as z:
    old_members = {i.filename: z.read(i.filename) for i in z.infolist()}
    old_bad = None
with zipfile.ZipFile(NEW) as z:
    new_members = {i.filename: z.read(i.filename) for i in z.infolist()}
    new_bad = z.testzip()

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(new_bad is None, "v29fix passes testzip()")
check(hashlib.sha256(old_raw).hexdigest().upper() == V28_SHA, "input really is v28fix")
check(list(old_members) == list(new_members),
      "member list and order unchanged (%d members)" % len(new_members))

print("\n== 2. only the two tables changed ==")
changed = [n for n in new_members if old_members[n] != new_members[n]]
check(changed == MEMBERS or sorted(changed) == sorted(MEMBERS),
      "changed members are exactly the two tables (%r)" % changed)
check(old_members[EXE] == new_members[EXE], "the executable is byte-identical")

print("\n== 3. the new members are valid OpenStep with the right value ==")
for name in MEMBERS:
    data = new_members[name]
    check(data.startswith(b"{") and data.rstrip().endswith(b"}"),
          "%s is brace-delimited" % name)
    check(all(b < 0x80 for b in data), "%s is pure ASCII (\\U escapes)" % name)
    check(b"\\U" in data, "%s actually uses \\U escapes" % name)
    try:
        table = parse_openstep(data)
    except Exception as ex:
        check(False, "%s did not decode: %s" % (name, ex))
        continue
    check(len(table) == 8, "%s has 8 entries (%d)" % (name, len(table)))
    check(table.get(FERT) == FERT_WANT,
          "%s: %r -> %r" % (name, FERT, table.get(FERT)))
    # and the raw UTF-8 must NOT be present (the ASCII reader would mojibake it)
    check(FERT_WANT.encode("utf-8") not in data,
          "%s does not embed raw UTF-8" % name)

print("\n== 4. the other seven values are unchanged from v28fix ==")
old_table = plistlib.loads(old_members[MEMBERS[0]])
new_table = parse_openstep(new_members[MEMBERS[0]])
for k in sorted(old_table):
    if k == FERT:
        continue
    check(old_table[k] == new_table.get(k),
          "%r: %r == %r" % (k, old_table[k], new_table.get(k)))
check(set(old_table) == set(new_table), "same key set")

print("\n== 5. the compressed slot is unchanged and still fits ==")
old_recs = {r["name"]: r for r in parse_zip_layout(old_raw)["records"]}
new_recs = {r["name"]: r for r in parse_zip_layout(new_raw)["records"]}
for name in MEMBERS:
    o, n = old_recs[name], new_recs[name]
    check(int(o["csize"]) == int(n["csize"]) == 189,
          "%s csize stays 189 (%d -> %d)" % (name, o["csize"], n["csize"]))
    check(int(n["usize"]) == len(new_members[name]),
          "%s usize matches the new data (%d)" % (name, n["usize"]))
    check(int(o["local_offset"]) == int(n["local_offset"]),
          "%s local offset unchanged (%#x)" % (name, o["local_offset"]))
    # verify the stored deflate stream really decompresses to the member data
    import zlib
    local = int(n["local_offset"])
    (sig, need, flag, method, mt, md, crc, csize, usize,
     nlen, elen) = struct.unpack_from("<I5H3I2H", new_raw, local)
    start = local + 30 + nlen + elen
    d = zlib.decompressobj(-15)
    plain = d.decompress(new_raw[start:start + csize])
    check(plain == new_members[name],
          "%s: stored stream decompresses to the member data" % name)
    check(zlib.crc32(plain) & 0xFFFFFFFF == crc, "%s: CRC matches" % name)
    check(len(plain) == usize, "%s: local usize matches" % name)

print("\n== 6. nothing else moved ==")
diff_ranges = []
for name in MEMBERS:
    local = int(old_recs[name]["local_offset"])
    (sig, need, flag, method, mt, md, crc, csize, usize,
     nlen, elen) = struct.unpack_from("<I5H3I2H", old_raw, local)
    diff_ranges.append((local + 14, local + 30 + nlen + elen + csize))
    central = int(old_recs[name]["offset"])
    diff_ranges.append((central + 16, central + 28))
covered = set()
for lo, hi in diff_ranges:
    covered |= set(range(lo, hi))
diff = {i for i in range(len(old_raw)) if old_raw[i] != new_raw[i]}
extra = sorted(diff - covered)
check(not extra, "no byte changed outside the declared ranges (%s)"
      % [hex(x) for x in extra[:8]])
check(len(diff) > 200, "the two members really were rewritten (%d bytes)" % len(diff))
for name in MEMBERS:
    check(old_recs[name]["crc"] != new_recs[name]["crc"],
          "%s CRC changed as expected" % name)

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

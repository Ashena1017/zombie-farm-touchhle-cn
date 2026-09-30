"""v19 recon E: the repaired Arial-BoldMT.strings member must still deflate into
its fixed 189-byte ZIP slot.  Try every practical deflate configuration, and if
none fits, measure how much a deduplicated bplist would save.
"""
import plistlib
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from patch_zfr_alert_fonts import parse_zip_layout  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v18fix.ipa"
NAME = "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings"

raw_ipa = IPA.read_bytes()
layout = parse_zip_layout(raw_ipa)
rec = None
for r in layout["records"]:
    if r["name"] == NAME:
        rec = r
print("slot csize = %d, usize = %d" % (rec["csize"], rec["usize"]))
print("record keys: %s" % sorted(rec))

with zipfile.ZipFile(IPA) as z:
    member = z.read(NAME)
    truth = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
    table = plistlib.loads(member)

pairs = {}
for k, v in table.items():
    c = truth[k]
    if v != c:
        pairs[v.encode("utf-16-be")] = c.encode("utf-16-be")
data = member
for a, b in pairs.items():
    data = data.replace(a, b)
print("patched member: %d bytes (raw %d)" % (len(data), len(member)))

best = None
for level in range(1, 10):
    for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED, zlib.Z_HUFFMAN_ONLY,
                     zlib.Z_RLE, zlib.Z_FIXED):
        for memlevel in (8, 9):
            for wbits in (-15, 15):
                co = zlib.compressobj(level, zlib.DEFLATED, wbits, memlevel, strategy)
                out = co.compress(data) + co.flush()
                if best is None or len(out) < best[0]:
                    best = (len(out), level, strategy, memlevel, wbits)
print("best deflate of the repaired member: %d bytes  (level=%d strategy=%d "
      "memLevel=%d wbits=%d)" % best)


def deflate(d, level=9, strategy=zlib.Z_DEFAULT_STRATEGY, memlevel=8, wbits=-15):
    co = zlib.compressobj(level, zlib.DEFLATED, wbits, memlevel, strategy)
    return co.compress(d) + co.flush()


print("\n-- can a deduplicated bplist be smaller? --")
# hand-build a bplist that SHARES the value object for the two identical values
vals = [truth[k] for k in table]
keys = list(table)
uniq = []
index = {}
for v in vals:
    if v not in index:
        index[v] = len(uniq)
        uniq.append(v)
print("values: %d total, %d unique" % (len(vals), len(uniq)))
print("plistlib round-trip size : %d -> deflate %d"
      % (len(plistlib.dumps(dict(zip(keys, vals)), fmt=plistlib.FMT_BINARY)),
         len(deflate(plistlib.dumps(dict(zip(keys, vals)), fmt=plistlib.FMT_BINARY)))))
for k, v in table.items():
    print("   %-24r broken=%d bytes  fixed=%r" % (k, len(v.encode("utf-16-be")),
                                                  truth[k]))

"""v19 recon G: how much can the repaired table shrink?  The slot is 189 bytes and
the faithful repair needs 193.  Measure a few equally-correct Chinese renderings.
"""
import plistlib
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from patch_zfr_alert_fonts import parse_zip_layout  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v18fix.ipa"
NAMES = ["Payload/ZFR.app/Arial-BoldMT.strings",
         "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings"]

raw_ipa = IPA.read_bytes()
layout = parse_zip_layout(raw_ipa)
slots = {r["name"]: r["csize"] for r in layout["records"]}

with zipfile.ZipFile(IPA) as z:
    truth = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
    table = plistlib.loads(z.read(NAMES[1]))


def deflate(d):
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(d) + co.flush()


for n in NAMES:
    print("%-52s slot=%d" % (n, slots[n]))

VARIANTS = {
    "faithful  ' %@施肥了'": {"Fertilized by %@!": " %@施肥了"},
    "no lead   '%@施肥了'": {"Fertilized by %@!": "%@施肥了"},
    "no 了     ' %@施肥'": {"Fertilized by %@!": " %@施肥"},
    "shortest  '%@施肥'": {"Fertilized by %@!": "%@施肥"},
}
print()
for label, over in VARIANTS.items():
    d = {k: over.get(k, truth[k]) for k in table}
    blob = plistlib.dumps(d, fmt=plistlib.FMT_BINARY, sort_keys=True)
    print("%-26s raw=%d deflate=%-4d %s"
          % (label, len(blob), len(deflate(blob)),
             "FITS" if len(deflate(blob)) <= min(slots.values()) else ""))
    assert plistlib.loads(blob) == d

print("\n-- does the key ORDER change the deflate size? (faithful text) --")
faithful = {k: truth[k] for k in table}
orders = {
    "member order": list(table),
    "sorted": sorted(table),
    "sorted by value": sorted(table, key=lambda k: truth[k]),
    "Zombie keys first": sorted(table, key=lambda k: ("Zombie" not in k, k)),
    "by value length": sorted(table, key=lambda k: (len(truth[k]), k)),
}
for label, order in orders.items():
    d = {k: faithful[k] for k in order}
    blob = plistlib.dumps(d, fmt=plistlib.FMT_BINARY, sort_keys=False)
    print("   %-20s raw=%d deflate=%-4d %s"
          % (label, len(blob), len(deflate(blob)),
             "FITS" if len(deflate(blob)) <= 189 else ""))

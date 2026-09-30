"""v17 recon F: recover the ORIGINAL text of the mojibake cstrings from the
untouched baseline, and show the usage site of ' +%dxxxx'.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

CUR = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
BASE = ROOT / "zombie_farm_ipa/ZFR 1.0.zh-CN-unsigned.ipa"
NEEDLE = b"ZFSaleEndDateDay"

with zipfile.ZipFile(CUR) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
with zipfile.ZipFile(BASE) as z:
    fatb = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    slb = next(s for s in parse_fat(fatb) if s.subtype == sub)
    sec = next(s for s in sl.sections if s.name == "__cstring")
    blob = sl.data[sec.offset:sec.offset + sec.size]
    p = blob.find(NEEDLE)
    print("\n=== sub%d" % sub)
    while p >= 0:
        e = blob.find(b"\0", p)
        print("   cur  @%#010x  %r" % (sec.addr + p, blob[p:e]))
        p = blob.find(NEEDLE, p + 1)

    secb = next(s for s in slb.sections if s.name == "__cstring")
    blobb = slb.data[secb.offset:secb.offset + secb.size]
    p = blobb.find(NEEDLE)
    while p >= 0:
        e = blobb.find(b"\0", p)
        raw = blobb[p:e]
        print("   base @%#010x  %r" % (secb.addr + p, raw))
        try:
            print("        utf-8: %r" % raw.decode("utf-8"))
        except Exception as ex:
            print("        utf-8: <undecodable %s>" % ex)
        print("        hex  : %s" % raw.hex())
        p = blobb.find(NEEDLE, p + 1)

import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    print("\n=== sub%d  len=%#x  sections=%d" % (sub, len(sl.data), len(sl.sections)))
    for sec in sl.sections:
        print("   %-16s addr=%#010x size=%#08x off=%#08x" % (sec.name, sec.addr, sec.size, sec.offset))
    a = 0x3A68D0 if sub == 9 else 0x46A940
    o = sl.addr_to_file(a)
    print("   CFString %#x -> file %s" % (a, o))
    if o:
        print("   bytes: %s" % sl.data[o:o + 32].hex())
        isa, flags, data, size = struct.unpack_from("<IIII", sl.data, o)
        print("   isa=%#x flags=%#x data=%#x size=%d" % (isa, flags, data, size))
        d = sl.addr_to_file(data)
        if d:
            print("   text=%r" % sl.data[d:d + 40])

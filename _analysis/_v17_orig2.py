"""v17 recon G: what did sub6 0x476190 / sub9 0x3b2120 point at in the BASELINE,
and what is the exact byte damage the codex patch did around 0x3d1c68?
Plus: disassemble the usage site in sub9.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

CUR = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
BASE = ROOT / "zombie_farm_ipa/ZFR 1.0.zh-CN-unsigned.ipa"

with zipfile.ZipFile(CUR) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
with zipfile.ZipFile(BASE) as z:
    fatb = z.read("Payload/ZFR.app/ZFR")

CF = {6: 0x476190, 9: 0x3B2120}
NEAR = {6: 0x3D1C68, 9: 0x30DC68}

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    slb = next(s for s in parse_fat(fatb) if s.subtype == sub)
    print("\n" + "=" * 74)
    print("sub%d   CFString %#x" % (sub, CF[sub]))
    for tag, s in (("cur ", sl), ("base", slb)):
        o = s.addr_to_file(CF[sub])
        if o is None:
            print("   %s : <not mapped>" % tag)
            continue
        isa, flags, data, size = struct.unpack_from("<IIII", s.data, o)
        od = s.addr_to_file(data)
        txt = s.data[od:od + 40].split(b"\0")[0] if od is not None else b"?"
        print("   %s : isa=%#x flags=%#x data=%#010x size=%d  -> %r"
              % (tag, isa, flags, data, size, txt))

    print("\n   __cstring around %#x:" % NEAR[sub])
    for tag, s in (("cur ", sl), ("base", slb)):
        o = s.addr_to_file(NEAR[sub] - 16)
        blob = s.data[o:o + 64]
        print("   %s : %s" % (tag, blob.hex()))
        print("         %r" % blob)

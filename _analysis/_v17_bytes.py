"""v17 recon H: collect the exact original bytes/hashes the v17 patcher must assert."""
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from patch_zfr_ability_v13 import thumb_branch  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

sl = {s.subtype: s for s in parse_fat(fat)}


def rd(sub, addr, n):
    s = sl[sub]
    o = s.addr_to_file(addr)
    return s.data[o:o + n]


print("sub9 0x54272 (call site)      :", rd(9, 0x54272, 4).hex(),
      "  expect thumb_branch BLX =", thumb_branch(0x54272, 0x2D014C, True).hex())
print("sub9 0x1138A0 cave[0:48]      :", rd(9, 0x1138A0, 48).hex())
print("   sha256[0:37]               :", hashlib.sha256(rd(9, 0x1138A0, 37)).hexdigest())
print("sub6 0x177534 cave[0:16]      :", rd(6, 0x177534, 16).hex())
print("   sha256[0:11]               :", hashlib.sha256(rd(6, 0x177534, 11)).hexdigest())

for sub, obj in ((6, 0x476190), (9, 0x3B2120)):
    f = rd(sub, obj, 16)
    isa, flags, data, size = struct.unpack("<IIII", f)
    print("sub%d CFSTR %#x : data=%#x size=%d  raw=%s" % (sub, obj, data, size, f.hex()))

# prove our BL encoder round-trips against the existing 0x5425c blx
print("\ncheck thumb_branch(0x5425C, 0x2D014C, True) =",
      thumb_branch(0x5425C, 0x2D014C, True).hex(), "file:", rd(9, 0x5425C, 4).hex())
print("check thumb_branch(0x54272, 0x1138A0, False) =",
      thumb_branch(0x54272, 0x1138A0, False).hex())
print("check thumb_branch(0x1138A4, 0x15140, False) =",
      thumb_branch(0x1138A4, 0x15140, False).hex())

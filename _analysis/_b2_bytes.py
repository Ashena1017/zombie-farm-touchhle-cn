"""Collect the exact original bytes v16 will overwrite."""
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v15fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

WANT = {
    6: [(0x263E74, 48, "printEvents cave (string storage)"),
        (0x468B88, 8, "CFString +%i field"),
        (0x468EE8, 8, "CFString -%i field"),
        (0x468EF8, 8, "CFString +%ixp field"),
        (0x469388, 8, "CFString %d field")],
    9: [(0x10C470, 22, "zfrLocFormat stub (v15)"),
        (0x1C0318, 48, "printEvents cave (string storage)"),
        (0x3A4B18, 8, "CFString +%i field"),
        (0x3A4E78, 8, "CFString -%i field"),
        (0x3A4E88, 8, "CFString +%ixp field"),
        (0x3A5318, 8, "CFString %d field")],
}
for sub, items in WANT.items():
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    print("#### sub%d" % sub)
    for addr, n, note in items:
        o = sl.addr_to_file(addr)
        raw = sl.data[o:o + n]
        print("   %#010x  len=%-3d %-34s %s" % (addr, n, note, raw.hex()))
        if n == 8:
            d, s = struct.unpack_from("<II", raw)
            print("        data=%#x size=%d" % (d, s))
        else:
            print("        sha256=%s" % hashlib.sha256(raw).hexdigest())

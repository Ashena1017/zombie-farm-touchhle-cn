"""Locate the CFString structs whose data points at the __const mojibake, find
who uses them, and check the same region in the untouched baseline."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v15fix.ipa"
BASE = ROOT / "zombie_farm_ipa/ZFR 1.0.zh-CN-unsigned.ipa"
TARGETS = {6: [0x406E00, 0x406E08, 0x406E10, 0x406E18, 0x4675E0],
           9: [0x342E00, 0x342E08, 0x342E10, 0x342E18]}

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
with zipfile.ZipFile(BASE) as z:
    fat_base = z.read("Payload/ZFR.app/ZFR")


def cs_(sl, a):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + 400)
    except ValueError:
        return None
    try:
        return sl.data[o:e].decode("utf-8")
    except Exception:
        return None


for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    slb = next(s for s in parse_fat(fat_base) if s.subtype == sub)
    print("\n" + "=" * 78)
    print("sub%d" % sub)
    print("=" * 78)
    for t in TARGETS[sub]:
        print("\n  --- references to %#x ---" % t)
        found = False
        for sec in sl.sections:
            blob = sl.data[sec.offset:sec.offset + sec.size]
            for i in range(0, len(blob) - 3):
                if struct.unpack_from("<I", blob, i)[0] == t:
                    a = sec.addr + i
                    print("     %-14s @%#010x" % (sec.name, a))
                    # if it looks like a CFString data field, show the struct
                    if sec.name in ("__cfstring", "__objc_cfstring"):
                        struct_addr = a - 8
                        isa = struct.unpack_from("<I", sl.data,
                                                 sl.addr_to_file(struct_addr))[0]
                        flags = struct.unpack_from("<I", sl.data,
                                                   sl.addr_to_file(struct_addr + 4))[0]
                        print("        -> CFString object %#x  isa=%#x flags=%#x  text=%r"
                              % (struct_addr, isa, flags, cs_(sl, t)))
                    elif sec.name == "__const":
                        print("        -> inside __const (probably a literal pool)")
                    found = True
        if not found:
            print("     (no 32-bit reference anywhere)")

    # what is the object at the CFString used as a table?
    if sub == 6:
        for addr in (0x4675E0,):
            o = sl.addr_to_file(addr)
            if o:
                isa, flags, data, size = struct.unpack_from("<IIII", sl.data, o)
                print("\n  CFString %#x: isa=%#x flags=%#x data=%#x size=%d text=%r"
                      % (addr, isa, flags, data, size, cs_(sl, data)))
                print("     baseline has this object? %s"
                      % (slb.addr_to_file(addr) is not None))

    # the baseline equivalent region
    print("\n  baseline __const around the same place:")
    o = slb.addr_to_file(TARGETS[sub][0] - 32)
    if o:
        print("     %s" % slb.data[o:o + 96].hex())
        print("     printable: %s" % "".join(
            chr(b) if 32 <= b < 127 else "." for b in slb.data[o:o + 96]))

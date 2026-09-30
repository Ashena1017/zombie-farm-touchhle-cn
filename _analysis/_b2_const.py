"""The mojibake actually lives in __const (my earlier scans only covered
__cstring/__objc_methname/__ustring).  Dump the region, work out the structure,
and sweep the whole segment in both slices."""
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

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
with zipfile.ZipFile(BASE) as z:
    fat_base = z.read("Payload/ZFR.app/ZFR")

REGIONS = {6: (0x406DC0, 0x406E80), 9: (0x342DC0, 0x342E80)}
for sub, (lo, hi) in REGIONS.items():
    print("=" * 78)
    print("sub%d  %#x..%#x  raw words" % (sub, lo, hi))
    print("=" * 78)
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    slb = next(s for s in parse_fat(fat_base) if s.subtype == sub)
    for a in range(lo, hi, 4):
        o = sl.addr_to_file(a)
        v = struct.unpack_from("<I", sl.data, o)[0] if o is not None else None
        # printable rendering of the 4 bytes
        raw = sl.data[o:o + 4]
        s = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
        sec = None
        for x in sl.sections:
            if x.addr <= a < x.addr + x.size:
                sec = x.name
        # does the same address in the baseline hold the same bytes?
        ob = slb.addr_to_file(a)
        base_raw = slb.data[ob:ob + 4] if ob is not None else b""
        same = "  =" if base_raw == raw else "  DIFFERS from baseline"
        print("   %#010x  %-10s %#010x  |%s|%s" % (a, sec, v or 0, s, same))
    print("   baseline bytes in the same range:")
    ob = slb.addr_to_file(lo)
    print("      %s" % slb.data[ob:ob + (hi - lo)].hex())

print()
print("=" * 78)
print("every __const string with Latin Extended-A, both slices")
print("=" * 78)
import re
for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    print("  sub%d:" % sub)
    for sec in sl.sections:
        if sec.name != "__const":
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        p = 0
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            if e > p:
                try:
                    s = blob[p:e].decode("utf-8")
                except Exception:
                    s = None
                if s and any(0x0100 <= ord(c) <= 0x024F for c in s):
                    print("     %#010x  %r  (%d bytes + NUL)" % (sec.addr + p, s, e - p))
            p = e + 1
        # also: printable runs that are not NUL terminated yet contain mojibake
        for m in re.finditer(rb"[\x20-\x7e\uc4\uc5\xc4\xc5\xe4-\xe9]{2,40}", blob):
            try:
                s = m.group().decode("utf-8")
            except Exception:
                continue
            if any(0x0100 <= ord(c) <= 0x024F for c in s):
                print("     %#010x  %r   (run, no NUL scan match)" % (sec.addr + m.start(), s))

"""Last two facts before building v16:
  A) sub9's ZFMarketMenu alertWindow:dismissedPositive: extent + any '%@ Used!' use
  B) a free zero run big enough for the 39 bytes of corrected UTC-8 strings
"""
import bisect
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v15fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

print("=" * 74)
print("A) method extent")
print("=" * 74)
for sub, imp in ((9, 0x54140), (6, 0x73778)):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    cb = classes_by_name(sl)
    starts = sorted({m.imp & ~1 for _cn, (c, info) in cb.items()
                     for m in all_methods(sl, c, info) if m.imp})
    i = bisect.bisect_right(starts, imp)
    nxt = starts[i] if i < len(starts) else None
    print("   sub%d ZFMarketMenu -alertWindow:dismissedPositive:  %#x .. %s  (%s bytes)"
          % (sub, imp, hex(nxt) if nxt else "?", nxt - imp if nxt else "?"))

print()
print("=" * 74)
print("B) free zero runs (>= 48 bytes) in __const / __cstring / __text tail")
print("=" * 74)
for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    print("   sub%d:" % sub)
    for sec in sl.sections:
        if sec.name not in ("__const", "__cstring", "__objc_const"):
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        for m in re.finditer(rb"\x00{48,}", blob):
            print("      %-14s %#010x  %d zero bytes"
                  % (sec.name, sec.addr + m.start(), m.end() - m.start()))
    # dead methods from the earlier census, as fallback caves
    text = next(s for s in sl.sections if s.name == "__text")
    cb = classes_by_name(sl)
    starts = sorted({m.imp & ~1 for _cn, (c, info) in cb.items()
                     for m in all_methods(sl, c, info) if m.imp})
    for name in ("displayMessage:atPosition:withColor:withDelay:withScroll:withScale:",
                 "backupSaveFiles", "printEvents", "fadeOutAllButtons"):
        for cn, (c, info) in cb.items():
            for m in all_methods(sl, c, info):
                if m.selector == name and m.imp:
                    a = m.imp & ~1
                    i = bisect.bisect_right(starts, a)
                    nxt = starts[i] if i < len(starts) else a + 64
                    print("      dead? %-24s %s -%s  %#x (+%d)"
                          % ("", cn, name[:28], a, nxt - a))

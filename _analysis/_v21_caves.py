"""Find free (zero/0xff filled) runs inside __text that are NOT inside any
previously claimed cave, for new stub code.

    python _v21_caves.py [min_len]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 40

FORBIDDEN = {
    6: [(0x1B464, 0x1B810), (0x16A5F8, 0x16A70C), (0x16D594, 0x16D5AC),
        (0x16D5B0, 0x16D5E0), (0x177534, 0x17753F)],
    9: [(0x14F6C, 0x151C0), (0x10A1DC, 0x10A29C), (0x10C470, 0x10C486),
        (0x10C490, 0x10C4C0), (0x1138A0, 0x1138C5)],
}

for sub in (9, 6):
    a = Annotator(load(subtype=sub)) if sub == 9 else None
    print("=== sub%d ===" % sub)
    if a is None:
        continue
    txt = next(s for s in a.sl.sections if s.name == "__text")
    data = a.sl.data[txt.offset:txt.offset + txt.size]
    runs = []
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b in (0x00, 0xFF):
            j = i
            while j < n and data[j] == b:
                j += 1
            if j - i >= MIN:
                runs.append((i, j - i, b))
            i = j
        else:
            i += 1
    for off, ln, b in runs:
        addr = txt.addr + off
        bad = any(addr < hi and lo < addr + ln for lo, hi in FORBIDDEN[sub])
        print("   %#08x len=%4d fill=%02x %s" % (addr, ln, b, "FORBIDDEN" if bad else ""))

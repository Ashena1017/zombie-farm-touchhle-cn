"""Print the current bytes + decoded float at the planned v21 sites."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import load

SITES = [
    (6, 0x0A31A4, 4, "#2 sub6 ZFAlertWindow -alertWindowSlideInInformative: title fontSize (mov r3,#imm)"),
    (6, 0x0A3464, 4, "#2 sub6 ... body1 fontSize (mov r3,#imm)"),
    (6, 0x11EFC4, 4, "#8 sub6 ZFZombieMenu -initLowerMenu 陵墓 fontSize (mov r3,#imm)"),
    (6, 0x1AAE94, 4, "revert v18 sub6 ZFAlertWindowStorageItem makeWindow arg"),
    (9, 0x076B7A, 4, "#2 sub9 title movt"),
    (9, 0x076DE8, 4, "#2 sub9 body1 movt"),
    (9, 0x0D290A, 4, "#8 sub9 陵墓 movt"),
    (9, 0x139D16, 4, "revert v18 sub9 makeWindow arg movt"),
]

for sub in (9, 6):
    sl = load(subtype=sub)
    print("=== sub%d ===" % sub)
    for s, addr, ln, note in SITES:
        if s != sub:
            continue
        o = sl.addr_to_file(addr)
        b = sl.data[o:o + ln]
        print("  %#010x  %s  raw=%s  %s" % (addr, b.hex(), struct.unpack("<I", b)[0], note))

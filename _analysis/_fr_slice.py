#!/usr/bin/env python3
"""Confirm which fat slice touchHLE actually executes, and check the two
load-bearing facts on THAT slice.

The log says:
    touchHLE::mach_o: Loading armv7 slice for "ZFR"
so the running code is whichever slice has cpusubtype == CPU_SUBTYPE_ARM_V7.
For Mach-O ARM: CPU_SUBTYPE_ARM_V6 = 6, CPU_SUBTYPE_ARM_V7 = 9.
"""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402

IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa"

CPU_SUBTYPE = {
    0: "ARM_ALL",
    5: "ARM_V4T",
    6: "ARM_V6",
    7: "ARM_V5TEJ",
    8: "ARM_XSCALE",
    9: "ARM_V7",
    10: "ARM_V7F",
    11: "ARM_V7S",
    12: "ARM_V7K",
    14: "ARM_V7M",
    15: "ARM_V7EM",
}


def main():
    with zipfile.ZipFile(ROOT / IPA) as z:
        fat = z.read(EXECUTABLE)

    magic = struct.unpack_from(">I", fat, 0)[0]
    nfat = struct.unpack_from(">I", fat, 4)[0]
    print(f"fat magic={magic:#x} (0xcafebabe = FAT_MAGIC)  nfat_arch={nfat}")
    print()
    for i in range(nfat):
        cputype, subtype, offset, size, align = struct.unpack_from(
            ">IIIII", fat, 8 + i * 20)
        print(f"  arch[{i}]: cputype={cputype} (12=ARM)  cpusubtype={subtype} "
              f"({CPU_SUBTYPE.get(subtype, '?')})  offset={offset:#x} size={size:#x}")

    print()
    for sl in parse_fat(fat):
        # The slice's own Mach-O header repeats cputype/cpusubtype.
        hcputype, hsubtype = struct.unpack_from("<ii", sl.data, 4)
        print(f"  Slice(subtype={sl.subtype}): header cpusubtype={hsubtype} "
              f"({CPU_SUBTYPE.get(hsubtype, '?')})")
        kind = "armv7  <== touchHLE RUNS THIS ONE" if hsubtype == 9 else "armv6"
        print(f"      -> {kind}")


if __name__ == "__main__":
    main()

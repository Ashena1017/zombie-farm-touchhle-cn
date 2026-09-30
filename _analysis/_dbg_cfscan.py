#!/usr/bin/env python3
"""Debug why the __cfstring scan missed an object _v17_cf.py reports."""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat                      # noqa: E402
from patch_zfr_alert_fonts import EXECUTABLE             # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data

print(f"len(data) = 0x{len(data):x}")
print(f"has addr_to_file: {hasattr(sl, 'addr_to_file')}")

for a in (0x3A4D40, 0x3A3310):
    print()
    print(f"--- raw 16 bytes at VA 0x{a:x} ---")
    print("   ", data[a:a + 16].hex(" "))
    isa, flags, ptr, ln = struct.unpack_from("<IIII", data, a)
    print(f"    isa=0x{isa:08x} flags=0x{flags:08x} data=0x{ptr:08x} len={ln}")
    if 0 < ptr < len(data) and 0 < ln < 4096 and ptr + ln <= len(data):
        print(f"    bytes: {data[ptr:ptr + ln]!r}")
    else:
        print("    (data pointer out of range)")

# What does addr_to_file say?
if hasattr(sl, "addr_to_file"):
    for a in (0x3A4D40, 0x2FAAC4):
        try:
            print(f"addr_to_file(0x{a:x}) = 0x{sl.addr_to_file(a):x}")
        except Exception as exc:                          # noqa: BLE001
            print(f"addr_to_file(0x{a:x}) raised {exc}")

# How does _v17_cf.py enumerate? Mirror its approach.
print()
print("--- scanning a narrow window around 0x3a4d40 with the flags check relaxed ---")
for off in range(-8, 9, 4):
    a = 0x3A4D40 + off
    isa, flags, ptr, ln = struct.unpack_from("<IIII", data, a)
    note = ""
    if 0 < ptr < len(data) and 0 < ln < 4096 and ptr + ln <= len(data):
        try:
            s = data[ptr:ptr + ln].decode("utf-8")
            note = repr(s)
        except UnicodeDecodeError as exc:
            note = f"<decode error {exc}>"
    print(f"    0x{a:08x}  isa=0x{isa:08x} flags=0x{flags:08x} ptr=0x{ptr:08x} len={ln:<5} {note}")

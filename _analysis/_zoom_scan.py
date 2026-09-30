# -*- coding: utf-8 -*-
"""Scan the ZFR Mach-O binary for zoom / pinch / gesture related strings and selectors."""
import re
import sys

BIN = sys.argv[1] if len(sys.argv) > 1 else r"<PATH-TO-EXTRACTED-ZFR-BIN>"

data = open(BIN, "rb").read()
print("binary size:", len(data))

# --- 1. plain ASCII string sweep (C strings, ObjC names/selectors are NUL-terminated) ---
strings = []
for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
    s = m.group().decode("ascii")
    strings.append((m.start(), s))

print("total ascii strings:", len(strings))

PATTERNS = [
    "Pinch", "pinch", "Zoom", "zoom", "Magnif", "magnif",
    "Gesture", "gesture", "Scale", "scale",
    "doubleTap", "DoubleTap", "twoFinger", "TwoFinger",
    "TouchesBegan", "touchesBegan",
]

print("\n=== keyword hits ===")
hits = {}
for off, s in strings:
    for p in PATTERNS:
        if p in s:
            hits.setdefault(p, []).append((off, s))
            break

for p in PATTERNS:
    lst = hits.get(p, [])
    print(f"\n--- {p}: {len(lst)} ---")
    seen = set()
    for off, s in lst[:60]:
        if s in seen:
            continue
        seen.add(s)
        print(f"  0x{off:08x}  {s[:120]}")

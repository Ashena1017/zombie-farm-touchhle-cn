#!/usr/bin/env python3
"""Resolve a contradiction about which .strings table feeds 'Fertilized by %@!'.

The v29fix report claims the float comes from the Arial-BoldMT.strings table
(v19 repaired that table and the mojibake went away; v29 changed it and the human
saw the new text in game).

The zombie-fertilize investigation claims the call site passes an EMPTY table name,
i.e. the DEFAULT table (Localizable.strings), which would mean v29fix changed the
wrong file.

Both cannot be true. This script gathers the raw facts:
  1. which tables contain the key at all, and with what value;
  2. what the executable actually passes in the `table:` argument.

Read-only.
"""
from __future__ import annotations

import plistlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
KEY = "Fertilized by %@!"


def load_strings(blob: bytes):
    """Parse a .strings member: binary plist, XML plist, or OpenStep text."""
    if blob[:8] == b"bplist00":
        return plistlib.loads(blob), "binary plist"
    if blob.lstrip()[:5] in (b"<?xml", b"<plist"):
        return plistlib.loads(blob), "XML plist"
    # OpenStep: { "k" = "v"; ... } with \Uxxxx escapes.
    text = blob.decode("ascii", "replace")
    out = {}
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text):
        def unesc(s: str) -> str:
            s = re.sub(r"\\U([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), s)
            return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        out[unesc(m.group(1))] = unesc(m.group(2))
    return out, "OpenStep text"


print("=" * 78)
print("1. which .strings tables contain the key")
print("=" * 78)
with zipfile.ZipFile(IPA) as z:
    names = [n for n in z.namelist() if n.endswith(".strings")]
    for n in sorted(names):
        try:
            table, fmt = load_strings(z.read(n))
        except Exception as exc:                      # noqa: BLE001
            print(f"  {n:<62} PARSE FAIL {exc}")
            continue
        if KEY in table:
            val = table[KEY]
            cps = " ".join(f"{ord(c):04X}" for c in val)
            print(f"  {n}")
            print(f"      format = {fmt}")
            print(f"      value  = {val!r}")
            print(f"      codepts= {cps}")
        else:
            print(f"  {n:<62} (no such key)")

print()
print("=" * 78)
print("2. what the call site passes as `table:`")
print("=" * 78)

from audit_zfr_ipa import parse_fat                     # noqa: E402
from patch_zfr_alert_fonts import EXECUTABLE            # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs     # noqa: E402

with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)

sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data

# The site the v29 report and the investigation both name.
SITE = 0x2A0D2
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

print(f"  sub9 disassembly around 0x{SITE:x}:")
for ins in md.disasm(data[SITE - 0x10: SITE + 0x28], SITE - 0x10):
    print(f"    0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

print()
print("  The `table:` argument is r3 for localizedStringForKey:value:table:")
print("  (r0=self, r1=SEL, r2=key, r3=value, [sp]=table)  <-- check the real ABI")
print()

# Show the surrounding method entry so the argument setup is visible.
print("  wider window 0x2a060..0x2a0f0:")
for ins in md.disasm(data[0x2A060: 0x2A0F0], 0x2A060):
    mark = "   <-- table-ish" if ins.address in (0x2A0D2, 0x2A0D8, 0x2A0DC) else ""
    print(f"    0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}{mark}")

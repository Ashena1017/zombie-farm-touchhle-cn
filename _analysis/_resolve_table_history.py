#!/usr/bin/env python3
r"""Decide which .strings table feeds the fertilize float -- by history.

The two candidate tables disagree in the shipped v29fix IPA:

    zh-Hans.lproj/Localizable.strings  ->  ' %@施肥了'   (了)
    zh-Hans.lproj/Arial-BoldMT.strings ->  ' %@施肥啦！' (啦！)

The human reports seeing the text from v29fix, i.e. '啦！'. That alone says the
table is Arial-BoldMT. This script confirms it independently, from the one piece of
history that cannot lie:

    BEFORE v19, the human saw MOJIBAKE ('%@ČđĂ') in this exact float.
    v19 only ever touched Arial-BoldMT.strings.
    So if Localizable.strings held CORRECT text throughout, the mojibake the human
    saw can only have come from Arial-BoldMT.strings.

Read-only.
"""
from __future__ import annotations

import plistlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"

# v18 is the last version BEFORE v19 touched the tables; v19 is the fix; the
# untouched baseline shows what codex started from.
VERSIONS = [
    ("baseline (unsigned)", Z / "ZFR 1.0.zh-CN-unsigned.ipa"),
    ("v18fix (pre-v19)", Z / f"{BASE}.fixed-fonts-v18fix.ipa"),
    ("v19fix", Z / f"{BASE}.fixed-fonts-v19fix.ipa"),
    ("v29fix (current)", Z / f"{BASE}.fixed-fonts-v29fix.ipa"),
]

KEY = "Fertilized by %@!"
TABLES = [
    "Payload/ZFR.app/Arial-BoldMT.strings",
    "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings",
    "Payload/ZFR.app/zh-Hans.lproj/Localizable.strings",
]


def load_strings(blob: bytes):
    if blob[:8] == b"bplist00":
        return plistlib.loads(blob), "bplist"
    if blob.lstrip()[:5] in (b"<?xml", b"<plist"):
        return plistlib.loads(blob), "xml"
    text = blob.decode("ascii", "replace")
    out = {}
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text):
        def unesc(s: str) -> str:
            s = re.sub(r"\\U([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), s)
            return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        out[unesc(m.group(1))] = unesc(m.group(2))
    return out, "openstep"


def is_mojibake(s: str) -> bool:
    """The codex damage looked like '%@ČđĂ': Latin Extended-A where CJK belongs."""
    return any(0x0100 <= ord(c) <= 0x02FF for c in s)


print("=" * 78)
print("value of 'Fertilized by %@!' per table, per version")
print("=" * 78)
print()

for label, path in VERSIONS:
    if not path.exists():
        print(f"  {label:<22} (file missing: {path.name})")
        continue
    print(f"  {label}   [{path.name}]")
    with zipfile.ZipFile(path) as z:
        present = set(z.namelist())
        for t in TABLES:
            short = t.replace("Payload/ZFR.app/", "")
            if t not in present:
                print(f"      {short:<44} (member absent)")
                continue
            try:
                table, fmt = load_strings(z.read(t))
            except Exception as exc:                       # noqa: BLE001
                print(f"      {short:<44} PARSE FAIL: {exc}")
                continue
            if KEY not in table:
                print(f"      {short:<44} (no such key)   [{fmt}]")
                continue
            val = table[KEY]
            flag = "  <== MOJIBAKE" if is_mojibake(val) else ""
            print(f"      {short:<44} {val!r:<24} [{fmt}]{flag}")
    print()

print("=" * 78)
print("verdict")
print("=" * 78)
print("""
  If, before v19, Localizable.strings already held CORRECT text while the human saw
  mojibake, then the float cannot have been reading Localizable.strings -- it was
  reading Arial-BoldMT.strings. v19 changed only the latter and the mojibake went
  away; v29 changed only the latter and the human saw the new wording. Both point
  the same way.
""")

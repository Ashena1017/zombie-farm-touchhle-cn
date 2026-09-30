# -*- coding: utf-8 -*-
"""Disassemble around setMultipleTouchEnabled: call sites to read the argument (YES/NO)."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(fat) if s.subtype == 9][0]
text = next(s for s in sl.sections if s.name == "__text")
code = sl.data[text.offset:text.offset + text.size]

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

for center in (0x125f10, 0x126e12, 0x212456):
    lo = center - 0x40
    start = lo - text.addr
    print(f"\n================ around 0x{center:x} ================")
    for ins in md.disasm(code[start:start + 0x60], lo):
        mark = "   <<< CALL" if ins.address == center else ""
        print(f"  0x{ins.address:06x}  {ins.mnemonic:<10} {ins.op_str}{mark}")

# -*- coding: utf-8 -*-
"""Decode the vmov immediates + look for initial zoomFactor/scale in initWithGameData:."""
import struct
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

print("=== raw 4-byte encodings of the vmov immediates ===")
for addr in (0x7e30, 0x7e78):
    off = text.offset + (addr - text.addr)
    raw = sl.data[off:off + 4]
    print(f"   0x{addr:x}: {raw.hex()}   ({' '.join(f'{b:02x}' for b in raw)})")

# decode with capstone, showing operand detail
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
for addr in (0x7e30, 0x7e78, 0x7e2c, 0x7e1a):
    off = text.offset + (addr - text.addr)
    for ins in md.disasm(sl.data[off:off + 4], addr):
        print(f"   0x{ins.address:x}: {ins.mnemonic} {ins.op_str}")
        for op in ins.operands:
            print(f"        op type={op.type} reg={ins.reg_name(op.reg) if op.type==1 else '-'} imm={op.imm if op.type==2 else '-'}")

print("\n=== initWithGameData: (0x4da9) — search for zoom/scale setup ===")
ranges = {m.selector: (m, s, e) for m, s, e in sl.method_ranges()}
m, start, end = ranges["initWithGameData:"]
print(f"   imp=0x{m.imp:x} range=[0x{start:x}, {hex(end) if end else '?'})")
size = (end - start) if end else 0x400
code = sl.data[text.offset + (start - text.addr): text.offset + (start - text.addr) + size]
for ins in md.disasm(code, start):
    if ins.mnemonic.startswith("v") or "scale" in ins.op_str.lower() or ins.mnemonic in ("str", "vstr"):
        print(f"   0x{ins.address:06x}  {ins.mnemonic:<10} {ins.op_str}")

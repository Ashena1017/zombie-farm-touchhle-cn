"""Brute-force the exact bytes for `vmov.f32 d16, #-27.0` (and a few other
candidates) starting from the real `vmov.f32 d16, #-6.0` at sub9 0x76d0e."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import load
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

sl = load("zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v23fix.ipa")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
ADDR = 0x76D0E
orig = sl.data[sl.addr_to_file(ADDR):sl.addr_to_file(ADDR) + 4]
print("orig %s -> %s" % (orig.hex(), " | ".join("%s %s" % (i.mnemonic, i.op_str)
                                               for i in md.disasm(orig, ADDR))))


def decode(code):
    ins = list(md.disasm(code, ADDR))
    return ins[0] if len(ins) == 1 else None


targets = {6.0: None, 27.0: None, -6.0: None, -27.0: None}
for hi in range(0x10000):
    code = orig[:2] + struct.pack("<H", hi)
    i = decode(code)
    if i is None or i.mnemonic.split(".")[0] != "vmov":
        continue
    s = i.op_str
    if not s.startswith("d16,"):
        continue
    for t in list(targets):
        if targets[t] is not None:
            continue
        try:
            val = float(s.split("#")[1].lstrip("+"))
        except ValueError:
            continue
        if abs(val - t) < 1e-9:
            targets[t] = code
print()
for t, code in sorted(targets.items()):
    if code is None:
        print("  %-6g  NOT FOUND" % t)
    else:
        i = decode(code)
        print("  %-6g  %s  %s %s" % (t, code.hex(), i.mnemonic, i.op_str))

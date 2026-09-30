"""Encode `vmov.f32 d16, #-27.0` by replacing the imm8 field of the existing
`vmov.f32 d16, #-6.0` at sub9 0x76d0e, and verify with capstone."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import load
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

sl = load("zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v23fix.ipa")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

for addr in (0x76D0E, 0x76D16, 0x76D12):
    o = sl.addr_to_file(addr)
    raw = sl.data[o:o + 4]
    ins = list(md.disasm(raw, addr))
    print("  %#010x  %s  %s" % (addr, raw.hex(),
                               " | ".join("%s %s" % (i.mnemonic, i.op_str) for i in ins)))

orig_addr = 0x76D0E
o = sl.addr_to_file(orig_addr)
orig = sl.data[o:o + 4]
print("\noriginal bytes %s" % orig.hex())


def vfp_imm8(v):
    """imm8 for a positive VFP modified immediate, or None."""
    s = 1 if v < 0 else 0
    v = abs(v)
    for i6 in (0, 1):
        for i54 in (0, 1, 2, 3):
            for i3210 in range(16):
                exp = ((0 if i6 else 1) << 7) | (i6 << 6) | (i6 << 5) | (i6 << 4) \
                    | (i6 << 3) | ((i54 >> 1) << 2) | (i54 & 1)
                frac = i3210 << 19
                val = struct.unpack("<f", struct.pack("<I", (s << 31) | (exp << 23) | frac))[0]
                if abs(val - v) < 1e-6:
                    return (s << 7) | (i6 << 6) | (i54 << 4) | i3210
    return None


print("\nimm8 for -6.0 : %s   -27.0 : %s" % (hex(vfp_imm8(-6.0) or 0), hex(vfp_imm8(-27.0) or 0)))

found = []
want = -27.0
cands = []
# the imm8 of VMOV.F32 (immediate) T2 is the low byte of the second halfword;
# verify every candidate by decoding it back with capstone
for v in range(256):
    b = bytearray(orig)
    b[2] = v
    ins = list(md.disasm(bytes(b), orig_addr))
    if len(ins) == 1 and ins[0].mnemonic.split(".")[0] == "vmov" and "27" in ins[0].op_str:
        cands.append((hex(v), bytes(b).hex(), "%s %s" % (ins[0].mnemonic, ins[0].op_str)))
print("\nbase candidates:")
for c in cands:
    print("   ", c)

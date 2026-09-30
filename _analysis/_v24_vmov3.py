"""Which bits of `vmov.f32 d16, #-6.0` form the immediate? Flip each bit and
watch the decoded constant, then synthesise the encoding for -27.0."""
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
base = int.from_bytes(orig, "little")


def decode(word):
    code = word.to_bytes(4, "little")
    ins = list(md.disasm(code, ADDR))
    if len(ins) != 1:
        return None
    return ins[0]


print("orig %#010x -> %s" % (base, decode(base).op_str))
print("\nbit flips that alter the immediate:")
imm_bits = {}
for i in range(32):
    i2 = decode(base ^ (1 << i))
    if i2 is None:
        print("  bit %2d -> undecodable" % i)
        continue
    print("  bit %2d -> %s %s" % (i, i2.mnemonic, i2.op_str))
    imm_bits[i] = i2.op_str

# The immediate is a VFP modified immediate: try to find a bit assignment that
# reproduces a requested value; we do it by brute force over the *immediate*
# bits only (the ones whose flip changed the printed constant).
cand_bits = [i for i in imm_bits]
print("\nimmediate field bits: %s" % cand_bits)


def brute(target, bits):
    n = len(bits)
    for v in range(1 << n):
        w = base
        for k, b in enumerate(bits):
            if (v >> k) & 1:
                w ^= (1 << b)
        i = decode(w)
        if i is None:
            continue
        s = i.op_str
        if not s.startswith("d16,") or "#" not in s:
            continue
        try:
            val = float(s.split("#")[1].lstrip("+"))
        except ValueError:
            continue
        if abs(val - target) < 1e-9:
            return w, i
    return None, None


for t in (27.0, -27.0, 30.0, -30.0):
    w, i = brute(t, cand_bits)
    print("  %-6g -> %s" % (t, ("%s  %s %s" % (w.to_bytes(4, 'little').hex(), i.mnemonic, i.op_str))
                            if w else "NOT FOUND"))

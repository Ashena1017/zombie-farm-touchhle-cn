"""v24 recon (sub6): where does `-initLowerMenu` get 'AmericanTypewriter-Bold'
from, and is that literal pool word shared?"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import load
from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

sl = load("zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v23fix.ipa",
          subtype=6)

# find the two font-name CFStrings in sub6
found = {}
for sec in sl.sections:
    if sec.name != "__cfstring":
        continue
    for off in range(0, sec.size, 16):
        addr = sec.addr + off
        isa, flags, data, ln = struct.unpack_from("<IIII", sl.data, sec.offset + off)
        if not (0x7C0 <= flags <= 0x7FF) or ln == 0 or ln > 64:
            continue
        o = sl.addr_to_file(data)
        if o is None:
            continue
        try:
            txt = sl.data[o:o + ln].decode("utf-8")
        except Exception:
            continue
        if txt.startswith("AmericanTypewriter"):
            found[txt] = addr
print("sub6 font CFStrings: %s" % {k: hex(v) for k, v in found.items()})

load_addr = 0x11EFC0       # `ldr r0, [pc, #0x21c]`  (base = Align(addr+8,4))
add_addr = 0x11EFD4        # `add r3, pc, r0`        (base = addr+8)
pool = ((load_addr + 8) & ~3) + 0x21C
word = struct.unpack("<I", sl.data[sl.addr_to_file(pool):sl.addr_to_file(pool) + 4])[0]
print("pool word @%#x = %#x -> target %#x" % (pool, word, (add_addr + 8 + word) & 0xFFFFFFFF))

# who else reads this pool word?
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True
txt = next(s for s in sl.sections if s.name == "__text")
readers = []
for x in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
    try:
        if not x.operands or not x.id:
            continue
    except Exception:
        continue
    if x.mnemonic.split(".")[0] != "ldr":
        continue
    if len(x.operands) < 2 or x.operands[1].type != ARM_OP_MEM:
        continue
    m = x.operands[1].mem
    if m.base == ARM_REG_PC and not m.index:
        if ((x.address + 8) & ~3) + (m.disp or 0) == pool:
            readers.append(x.address)
print("readers of that pool word: %s" % [hex(r) for r in readers])

# the de-bolded target
if "AmericanTypewriter" in found:
    new_target = found["AmericanTypewriter"]
    print("new word for %#x = %#x" % (new_target, (new_target - (add_addr + 8)) & 0xFFFFFFFF))

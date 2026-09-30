"""v17 recon D: settle the Thumb `add rd, pc` base rule.

The README says Thumb PC-relative bases are Align(addr+4,4).  Two sites in sub9
(ZFMarketMenu tooltip) only resolve to a valid CFString if the base is the
UNALIGNED addr+4.  Test statistically: for every 16-bit `add rd, pc` instruction
whose address is 2 mod 4, see which formula lands exactly on a known object.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,  # noqa: E402
                                ARM_REG_PC)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)

txt = next(s for s in sl.sections if s.name == "__text")
secs = [(s.addr, s.addr + s.size, s.name) for s in sl.sections if s.size and s.offset]


def sec_of(a):
    for lo, hi, n in secs:
        if lo <= a < hi:
            return n
    return None


cf = set()
sec = next(s for s in sl.sections if s.name == "__cfstring")
for off in range(0, sec.size - 16, 16):
    if struct.unpack_from("<I", sl.data, sec.offset + off + 4)[0] == 0x7C8:
        cf.add(sec.addr + off)
print("CFString objects: %d (base %#x)" % (len(cf), sec.addr))

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
ins = list(md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr))
print("instructions: %d" % len(ins))

regs = {}
stat = {"unaligned": 0, "aligned": 0, "both": 0, "neither": 0}
tot = {"addpc16": 0, "m2": 0, "m2_known": 0}
examples = []

for x in ins:
    if not x.id:
        regs = {}
        continue
    ops = x.operands
    m = x.mnemonic.split(".")[0]

    if m in ("movw", "movt") and ops and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        d = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        regs[d] = ((imm << 16) | ((regs.get(d) or 0) & 0xFFFF)) if m == "movt" else imm
        continue

    if m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
            ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
        d = ops[0].reg
        v = regs.get(d)
        tot["addpc16"] += 1
        if x.address % 4 == 2:
            tot["m2"] += 1
            if v is not None:
                tot["m2_known"] += 1
        if v is not None:
            u = (x.address + 4 + v) & 0xFFFFFFFF
            a = (((x.address + 4) & ~3) + v) & 0xFFFFFFFF
            if x.address % 4 == 2:
                hu, ha = u in cf, a in cf
                key = ("both" if hu and ha else "unaligned" if hu
                       else "aligned" if ha else "neither")
                stat[key] += 1
                if len(examples) < 20 and (hu or ha):
                    examples.append((x.address, v, u, sec_of(u), a, sec_of(a), key))
        regs[d] = None
        continue

    if m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mem = ops[1].mem
        if mem.base == ARM_REG_PC:
            idx = regs.get(mem.index) if mem.index else 0
            if idx is not None:
                eff = (x.address + 4 + (mem.disp or 0) + idx) & 0xFFFFFFFF
                o = sl.addr_to_file(eff)
                regs[ops[0].reg] = struct.unpack_from("<I", sl.data, o)[0] if o is not None else None
            else:
                regs[ops[0].reg] = None
        else:
            regs[ops[0].reg] = None
        continue

    if m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG:
        regs[ops[0].reg] = ops[1].imm if ops[1].type == ARM_OP_IMM else regs.get(ops[1].reg)
        continue

    if m in ("bl", "blx", "b", "bx"):
        if ops and ops[0].type == ARM_OP_IMM:
            for r in (0, 1, 2, 3, 12):
                regs.pop(r, None)
        continue

print("\ntotals: %r" % tot)
print("16-bit `add rd, pc` at addr%%4==2 with a known delta: %r" % stat)
print("(a CFString hit means the resolved address is exactly a CFString object)\n")
for e in examples:
    print("   add pc @%#010x  delta=%#010x  unaligned=%#010x (%s)   aligned=%#010x (%s)"
          % (e[0], e[1], e[2], e[3], e[4], e[5]))

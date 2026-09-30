"""v17 recon I: find every site that materialises an IEEE-754 float constant in a
slice, with the owning method -- so font sizes (12.0/14.0/18.0/19.0/24.0/...) can
be located for the remaining font issues.

usage: python _v17_floats.py <sub> <float> [<float> ...]
"""
import bisect
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
SUB = int(sys.argv[1], 0)
WANT = [float(x) for x in sys.argv[2:]] or [19.0]
WANT_BITS = {struct.unpack("<I", struct.pack("<f", v))[0]: v for v in WANT}

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == SUB)
thumb = SUB == 9
txt = next(s for s in sl.sections if s.name == "__text")

cb = classes_by_name(sl)
full = {}
for cn, (c, info) in cb.items():
    for m in all_methods(sl, c, info):
        if m.imp:
            full.setdefault(m.imp & ~1, []).append("%s %s" % (cn, m.selector))
starts = sorted(full)


def owner(a):
    i = bisect.bisect_right(starts, a) - 1
    if i < 0:
        return "?"
    if a - starts[i] > 0x3000:
        return "? (after %s)" % full[starts[i]][0]
    return "%s+%#x" % (full[starts[i]][0], a - starts[i])


md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
md.detail = True
md.skipdata = True

bounds = sorted(set(starts) | {txt.addr, txt.addr + txt.size})
ins_list = []
for lo, hi in zip(bounds, bounds[1:]):
    if not (txt.addr <= lo < txt.addr + txt.size):
        continue
    o = sl.addr_to_file(lo)
    if o is None:
        continue
    pos = 0
    blob = sl.data[o:o + min(hi - lo, 0x20000)]
    for x in md.disasm(blob, lo):
        ins_list.append(x)

print("sub%d: %d instructions, looking for %r" % (SUB, len(ins_list), WANT))
regs = {}
for i, ins in enumerate(ins_list):
    if not ins.id or not ins.operands:
        regs = {}
        continue
    ops = ins.operands
    m = ins.mnemonic.split(".")[0]
    dst = nv = None
    hit = None
    if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) if m == "movt" else imm
        hit = WANT_BITS.get(nv)
    elif m == "mov" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
        hit = WANT_BITS.get(nv)
    elif m == "orr" and len(ops) == 3 and ops[0].type == ARM_OP_REG and \
            ops[2].type == ARM_OP_IMM and ops[1].type == ARM_OP_REG:
        src = regs.get(ops[1].reg)
        if src is not None:
            dst = ops[0].reg
            nv = src | ops[2].imm
            hit = WANT_BITS.get(nv)
    elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
            ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
        dst = ops[0].reg
        pcw = (((ins.address + 4) & ~3) if thumb else (ins.address + 8))
        eff = pcw + (ops[1].mem.disp or 0)
        o = sl.addr_to_file(eff)
        if o is not None:
            nv = struct.unpack_from("<I", sl.data, o)[0]
            hit = WANT_BITS.get(nv)
    elif m in ("bl", "blx", "b"):
        if ops[0].type == ARM_OP_IMM and not (txt.addr <= ops[0].imm < txt.addr + txt.size):
            for r in (0, 1, 2, 3, 12):
                regs.pop(r, None)
    if hit is not None:
        print("   %-10s @%#010x  %-16s  %s"
              % ("%g" % hit, ins.address, owner(ins.address), ins.mnemonic + " " + ins.op_str))
    if dst is not None:
        regs[dst] = nv

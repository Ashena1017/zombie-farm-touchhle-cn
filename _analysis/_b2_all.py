"""Whole-slice scan: which code materialises these CFString objects, and what is
the next objc_msgSend after each materialisation?

Handles both idioms:
  ARM   : ldr rD,[pc,#imm] (delta) ; add rD, pc, rD      -> (addr+8) + delta
  Thumb : movw/movt rD             ; add rD, pc          -> Align(addr+4,4) + rD
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
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,  # noqa: E402
                                ARM_REG_PC)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"
TARGETS = {
    6: {0x46A940: "'%@ Used!'",
        0x468AD0: "'%@ (%i)            '",
        0x4686F0: "'%@ (%i)        '"},
    9: {0x3A68D0: "'%@ Used!'",
        0x3A4A60: "'%@ (%i)            '",
        0x3A4680: "'%@ (%i)        '"},
}

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    OBJC = 0x2D014C if thumb else 0x393FE0

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    cb = classes_by_name(sl)
    full = {}
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append(cn + " " + m.selector)
    starts = sorted(full)

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        return "%s+%#x" % (full[starts[i]][0], a - starts[i]) if i >= 0 else "?"

    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True

    # Walk method by method.  A single linear sweep desyncs on literal pools and
    # silently loses sites (the lesson recorded in README 5.x / _align_test.py).
    bounds = sorted(set(starts) | {txt.addr, txt.addr + txt.size})
    ins_list = []
    for lo, hi in zip(bounds, bounds[1:]):
        if not (txt.addr <= lo < txt.addr + txt.size):
            continue
        o = sl.addr_to_file(lo)
        if o is None:
            continue
        for x in md.disasm(sl.data[o:o + min(hi - lo, 0x20000)], lo):
            ins_list.append(x)
    print("\n########## sub%d  (%d instructions over %d methods)"
          % (sub, len(ins_list), len(bounds)))
    regs = {}
    for i, ins in enumerate(ins_list):
        if not ins.id or not ins.operands:
            regs = {}
            continue
        ops = ins.operands
        m = ins.mnemonic.split(".")[0]
        pc = ins.address + (4 if thumb else 8)
        dst = None
        nv = None
        hit = None

        def add_pc_delta(reg_holding_delta):
            v = regs.get(reg_holding_delta)
            if v is None:
                return None
            if thumb:
                return (((ins.address + 4) & ~3) + v) & 0xFFFFFFFF
            return (pc + v) & 0xFFFFFFFF

        if m == "add" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and \
                ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            # ARM  : add rD, pc, rX   -> delta in rX
            # Thumb: add rD, pc       -> delta in rD  (capstone may repeat pc)
            src = ops[2].reg if (not thumb and len(ops) == 3
                                 and ops[2].type == ARM_OP_REG) else ops[0].reg
            nv = add_pc_delta(src)
            if nv is not None:
                dst = ops[0].reg
                hit = TARGETS[sub].get(nv)
        elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            dst = ops[0].reg
            if mm.base == ARM_REG_PC:
                idx = regs.get(mm.index) if mm.index else 0
                if idx is None:
                    nv = None
                else:
                    eff = (pc + (mm.disp or 0) + idx) & 0xFFFFFFFF
                    nv = u32(eff)
                    # a PC-relative literal may hold the object address either
                    # directly or as a delta consumed by a following `add rX,pc`
                    hit = TARGETS[sub].get(eff) or TARGETS[sub].get(nv)
            else:
                nv = None
        elif m in ("movw", "movt") and ops[0].type == ARM_OP_REG and \
                len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            imm = ops[-1].imm & 0xFFFF
            if m == "movt":
                nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) & 0xFFFFFFFF
            else:
                nv = imm
        elif m == "mov" and ops[0].type == ARM_OP_REG and \
                len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            nv = ops[-1].imm
        elif m in ("bl", "blx", "b"):
            if ops[0].type == ARM_OP_IMM and not (txt.addr <= ops[0].imm < txt.addr + txt.size):
                for r in (0, 1, 2, 3, 12):
                    regs.pop(r, None)
            dst = None
        else:
            dst = None

        if hit:
            print("   %-24s materialise @ %#010x   %s" % (hit, ins.address, owner(ins.address)))
            for j in range(i + 1, min(i + 16, len(ins_list))):
                k = ins_list[j]
                if k.mnemonic in ("bl", "blx") and k.operands and \
                        k.operands[0].type == ARM_OP_IMM and \
                        (k.operands[0].imm & ~1) == OBJC:
                    print("        -> call @ %#010x  %-4s   %s"
                          % (k.address, k.mnemonic, owner(k.address)))
                    break
        if dst is not None:
            regs[dst] = nv

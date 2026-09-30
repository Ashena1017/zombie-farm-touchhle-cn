"""#4 v13: full-sweep PIC scan for materialisations of the two tool-count
CFStrings (sub9 0x3A4680 short / its long twin; sub6 0x4686F0 short).
Track movw/movt/add-pc/ldr-literal + reg-reg mov, but DO NOT clear on
internal calls (only on msgsend/struct-ret). Report sites where a register
holds the CFString address and the next msgsend/call target.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

TARGETS = {6: (0x4686F0,), 9: (0x3A4680,)}

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    txt = next(s for s in sl.sections if s.name == "__text")

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    def cs_(a, limit=80):
        o = sl.addr_to_file(a)
        if o is None:
            return None
        try:
            e = sl.data.index(b"\0", o, o + limit)
        except ValueError:
            return None
        try:
            s = sl.data[o:e].decode("utf-8")
        except Exception:
            return None
        return s if s and s.isprintable() else None

    sel_of = {}
    for sec in sl.sections:
        if sec.name != "__objc_selrefs":
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v:
                t = cs_(v)
                if t and not t.startswith("<addr"):
                    sel_of[a] = t
    name_of_cstr = {}
    for a, t in sel_of.items():
        name_of_cstr.setdefault(u32(a), t)

    MSGSEND = 0x2D014C if sub == 9 else 0x393FE0
    STRUCTRET = 0x2D0170 if sub == 9 else 0x394004

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    ins = list(md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr))
    regs = {}
    print("=== sub%d targets %s ===" % (sub, [hex(t) for t in TARGETS[sub]]))
    nhit = 0
    for i, x in enumerate(ins):
        if not x.id or not x.operands:
            regs = {}
            continue
        ops = x.operands
        m = x.mnemonic.split(".")[0]
        if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            imm = ops[-1].imm & 0xFFFF
            regs[dst] = imm if m == "movw" else ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF))
        elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
            regs[ops[0].reg] = regs.get(ops[1].reg)
        elif not thumb and m == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG:
            a = b = None
            for k, oo in ((1, ops[1]), (2, ops[2])):
                if oo.type == ARM_OP_REG and oo.reg == ARM_REG_PC:
                    v = x.address + 8
                elif oo.type == ARM_OP_REG:
                    v = regs.get(oo.reg)
                elif oo.type == ARM_OP_IMM:
                    v = oo.imm
                else:
                    v = None
                if k == 1:
                    a = v
                else:
                    b = v
            if a is not None and b is not None:
                regs[ops[0].reg] = (a + b) & 0xFFFFFFFF
        elif thumb and m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            v = regs.get(ops[0].reg)
            if v is not None:
                regs[ops[0].reg] = ((x.address + 4) + v) & 0xFFFFFFFF
        elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            if mm.base == ARM_REG_PC and not mm.index:
                base = ((x.address + 4) & ~3) if thumb else x.address + 8
                eff = (base + (mm.disp or 0)) & 0xFFFFFFFF
                regs[ops[0].reg] = u32(eff)
            elif mm.base == ARM_REG_PC and mm.index:
                idx = regs.get(mm.index)
                if idx is None:
                    regs[ops[0].reg] = None
                else:
                    base = ((x.address + 4) & ~3) if thumb else x.address + 8
                    regs[ops[0].reg] = u32((base + (mm.disp or 0) + idx) & 0xFFFFFFFF)
            elif mm.base in regs and regs[mm.base] is not None and not mm.index:
                regs[ops[0].reg] = u32((regs[mm.base] + (mm.disp or 0)) & 0xFFFFFFFF)
            else:
                regs[ops[0].reg] = None
        elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ops[-1].imm
        elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
            t = ops[0].imm & ~1
            if t in (MSGSEND, STRUCTRET):
                for r, v in regs.items():
                    if v in TARGETS[sub]:
                        r1 = regs.get(1)
                        nm = name_of_cstr.get(r1, sel_of.get(r1, "?")) if r1 is not None else "?"
                        print("  materialised in r%d @ %#x -> %s %#x (r1=%s)" % (
                            r, x.address, "msgsend" if t == MSGSEND else "structret", t, nm))
                        # context
                        for y in ins[max(0, i - 10):i]:
                            print("      %#010x  %-8s %s" % (y.address, y.mnemonic, y.op_str))
                        print("      %#010x  %-8s %s  <<<<" % (x.address, x.mnemonic, x.op_str))
                        nhit += 1
                        break
                for r in (0, 1, 2, 3, 12):
                    regs.pop(r, None)
            # internal calls: do NOT clear (may be stacked CFString args)
    print("  total %d" % nhit)

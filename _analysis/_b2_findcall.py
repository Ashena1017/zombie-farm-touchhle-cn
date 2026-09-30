"""For a given CFString literal, find the objc_msgSend call that consumes it.

Usage:  python _b2_findcall.py "<cfstring text>" [ipa]

It resolves the __cstring -> __cfstring -> code materialisation, then reports
every `bl/blx objc_msgSend` within a short window after the materialisation
together with the register that carries the format and whether a later
stringWithFormat: follows.  This is how the sub9 twins of the sub6 patch sites
are located without guessing offsets.
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

TEXT = sys.argv[1]
IPA = Path(sys.argv[2]) if len(sys.argv) > 2 else \
    ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    OBJC = 0x2D014C if thumb else 0x393FE0

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    def cs_(a):
        o = sl.addr_to_file(a)
        if o is None:
            return None
        try:
            e = sl.data.index(b"\0", o, o + 400)
        except ValueError:
            return None
        try:
            return sl.data[o:e].decode("utf-8")
        except Exception:
            return None

    cs2str = {}
    for sec in sl.sections:
        if sec.name != "__cstring":
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        p = 0
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            try:
                cs2str[sec.addr + p] = blob[p:e].decode("utf-8")
            except Exception:
                pass
            p = e + 1
    cf_target = set()
    for sec in sl.sections:
        if sec.name not in ("__cfstring", "__objc_cfstring"):
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v is not None and cs2str.get(v) == TEXT:
                cf_target.add(a - 8)

    selrefs = {}
    for sec in sl.sections:
        if sec.name != "__objc_selrefs":
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v:
                t = cs_(v)
                if t and not t.startswith("<addr"):
                    selrefs[a] = t

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
    ins_list = list(md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr))

    print("\n########## sub%d   CFString %r  objects=%s"
          % (sub, TEXT, [hex(x) for x in cf_target]))
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
        hit = False
        if m == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            # ARM:  add rD, pc, rX      -> (addr + 8) + rX
            v = regs.get(ops[2].reg) if ops[2].type == ARM_OP_REG else None
            if v is not None:
                nv = (pc + v) & 0xffffffff
                dst = ops[0].reg
                hit = nv in cf_target
        elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            # Thumb: add rD, pc         -> Align(addr + 4, 4) + rD
            v = regs.get(ops[0].reg)
            if v is not None:
                nv = (((ins.address + 4) & ~3) + v) & 0xffffffff
                dst = ops[0].reg
                hit = nv in cf_target
        elif m == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG:
            a = b = None
            for k, oo in ((1, ops[1]), (2, ops[2])):
                if oo.type == ARM_OP_REG and oo.reg == ARM_REG_PC:
                    v = pc
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
                nv = (a + b) & 0xffffffff
                dst = ops[0].reg
                hit = nv in cf_target
        elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            dst = ops[0].reg
            if mm.base == ARM_REG_PC:
                idx = regs.get(mm.index) if mm.index else 0
                if idx is None:
                    nv = None
                else:
                    eff = (pc + (mm.disp or 0) + idx) & 0xffffffff
                    nv = u32(eff)
                    hit = eff in cf_target
            else:
                nv = None
        elif m in ("mov", "movw", "movt") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
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
            print("   materialise @ %#010x  (%s)   %s" % (ins.address, dst and hex(dst), owner(ins.address)))
            for j in range(i + 1, min(i + 14, len(ins_list))):
                k = ins_list[j]
                if k.mnemonic in ("bl", "blx") and k.operands and \
                        k.operands[0].type == ARM_OP_IMM and \
                        (k.operands[0].imm & ~1) == OBJC:
                    print("        next objc_msgSend: %#010x  %-4s   %s"
                          % (k.address, k.mnemonic, owner(k.address)))
                    break
        if dst is not None:
            regs[dst] = nv

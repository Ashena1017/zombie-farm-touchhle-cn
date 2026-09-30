"""#4 diagnostics v2: emulate movw/movt/add-pc/ldr chains in ZFToolsLayer (sub9),
resolving absolute reads so objc_msgSend calls get selector names."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC,
                                ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
txt = next(s for s in sl.sections if s.name == "__text")


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a, limit=120):
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
    return s if s.isprintable() and s else None


selrefs = {}   # addr -> selector string
selval = {}    # pointer value -> selector string
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
                selval[v] = t

cb = classes_by_name(sl)
c, info = cb["ZFToolsLayer"]
methods = {m.selector: (m.imp & ~1) for m in all_methods(sl, c, info)}

MSGSEND = 0x2D014C

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

# float decode helper
def fstr(v):
    try:
        f = struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]
        if 0.5 <= abs(f) <= 100000 and f == f:  # plausible layout/float const
            return " (=%.4g float)" % f
    except Exception:
        pass
    return ""


def dis_method(sel, limit=0x600):
    imp = methods[sel]
    print("\n===== ZFToolsLayer %s @ %#x =====" % (sel, imp))
    o = sl.addr_to_file(imp)
    ins = list(md.disasm(sl.data[o:o + limit], imp))
    regs = {}   # reg -> int value or None
    where = {}  # reg -> description of how the value was derived
    for x in ins:
        if not x.id or not x.operands:
            regs = {}
            where = {}
            continue
        ops = x.operands
        m = x.mnemonic.split(".")[0]
        ann = ""
        dst = None
        nv = None
        nw = None
        if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            imm = ops[-1].imm & 0xFFFF
            if m == "movw":
                nv = imm
                nw = "imm"
            else:
                nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) & 0xFFFFFFFF
                nw = "imm"
                ann = fstr(nv)
        elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
            dst = ops[0].reg
            nv = regs.get(ops[1].reg)
            nw = where.get(ops[1].reg)
            if nv is not None and eff_sel(nv):
                ann = "SEL " + eff_sel(nv)
        elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
                and ops[1].reg == ARM_REG_PC:
            v = regs.get(ops[0].reg)
            if v is not None:
                dst = ops[0].reg
                nv = ((x.address + 4) + v) & 0xFFFFFFFF
                nw = "abs"
                if nv in selrefs:
                    ann = "SELREF " + selrefs[nv]
                else:
                    s = cs_(nv, 48)
                    if s:
                        ann = "CSTR %r" % s
        elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            dst = ops[0].reg
            if mm.base == ARM_REG_PC:
                pcw = (x.address + 4) & ~3
                idx = regs.get(mm.index) if mm.index else 0
                if idx is not None:
                    eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                    v = u32(eff)
                    nv = v
                    nw = "mem"
            else:
                base = regs.get(mm.base)
                if base is not None:
                    eff = (base + (mm.disp or 0)) & 0xFFFFFFFF
                    v = u32(eff)
                    nv = v
                    nw = "mem"
                    if eff in selrefs:
                        ann = "SEL " + selrefs[eff]
                        nw = "sel"
                    elif v is not None and v in selval:
                        ann = "SEL " + selval[v]
                        nw = "sel"
                    elif v is not None:
                        s = cs_(v, 48)
                        if s:
                            ann = "CSTR %r" % s
                        else:
                            ann = "@%#x=%#x%s" % (eff, v, fstr(v))
                    else:
                        ann = "@%#x=<unmapped>" % eff
        elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
            t = ops[0].imm & ~1
            if t == MSGSEND:
                r0v, r1v = regs.get(ARM_REG_R0), regs.get(ARM_REG_R1)
                r0w, r1w = where.get(ARM_REG_R0), where.get(ARM_REG_R1)
                nm = eff_sel(r1v) if r1v is not None else None
                ann = "MSGSEND r1=%s(%s) r0=%s(%s)" % (
                    nm or ("<%s>" % (hex(r1v) if r1v is not None else "?")), r1w,
                    hex(r0v) if r0v is not None else "?", r0w)
            elif txt.addr <= t < txt.addr + txt.size:
                ann = "internal %#x" % t
            else:
                ann = "call %#x" % t
            for r in (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12):
                regs.pop(r, None)
                where.pop(r, None)
            print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))
            continue
        elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            nv = ops[-1].imm
            nw = "imm"
            ann = fstr(nv)
        if dst is not None:
            regs[dst] = nv
            if nw:
                where[dst] = nw
            elif dst in where:
                del where[dst]
        # print interesting lines
        if ann or m in ("bl", "blx", "pop", "cbz", "cbnz", "b"):
            print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))


def eff_sel(v):
    return selval.get(v)


for sel in ("setToolLabel:", "showToolName:", "replaceActiveToolButton:"):
    dis_method(sel)

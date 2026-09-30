"""#4 v5: scan ZFToolsLayer -init (sub9) for toolName label creation + setPosition: flow."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods, read_ivars
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC,
                                ARM_REG_R0, ARM_REG_R1)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
txt = next(s for s in sl.sections if s.name == "__text")


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def f32(a):
    v = u32(a)
    return struct.unpack("<f", struct.pack("<I", v))[0] if v is not None else None


def cs_(a, limit=160):
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


selref_at = {}
selval = {}
for sec in sl.sections:
    if sec.name != "__objc_selrefs":
        continue
    for off in range(0, sec.size, 4):
        a = sec.addr + off
        v = u32(a)
        if v:
            t = cs_(v)
            if t and not t.startswith("<addr"):
                selref_at[a] = t
                selval[v] = t

cb = classes_by_name(sl)
c, info = cb["ZFToolsLayer"]
ivar_list = read_ivars(sl, info.get("ivars"))
ivars = {iv["offset"]: iv["name"] for iv in ivar_list}
methods = {m.selector: (m.imp & ~1) for m in all_methods(sl, c, info)}

MSGSEND = 0x2D014C
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

imp = methods["init"]
o = sl.addr_to_file(imp)
# init is big; disasm 0x1200 bytes
code = sl.data[o:o + 0x1300]
ins = list(md.disasm(code, imp))
regs = {}
fregs = {}  # s-reg num -> float value
for x in ins:
    if not x.id or not x.operands:
        regs = {}
        continue
    ops = x.operands
    m = x.mnemonic.split(".")[0]
    ann = ""
    show = False
    dst = None
    nv = None
    if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = imm if m == "movw" else ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF))
        if m == "movt" and nv is not None and nv in selval:
            ann = "SEL? " + selval[nv]
    elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
        if nv is not None and nv in selval:
            ann = "SEL " + selval[nv]
    elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
    elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
            and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if v is not None:
            dst = ops[0].reg
            nv = ((x.address + 4) + v) & 0xFFFFFFFF
            if nv in selref_at:
                ann = "SELREF " + selref_at[nv]
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
                if eff in selref_at:
                    ann = "SEL " + selref_at[eff]
                elif v is not None and v in selval:
                    ann = "SEL " + selval[v]
                elif v is not None:
                    s = cs_(v, 64)
                    if s:
                        ann = "CSTR %r" % s
                    if v in ivars:
                        ann += " [ivar %s +0x%x]" % (ivars[v], v)
        else:
            base = regs.get(mm.base)
            if base is not None:
                eff = (base + (mm.disp or 0)) & 0xFFFFFFFF
                if eff in selref_at:
                    ann = "SEL " + selref_at[eff]
                    nv = u32(eff)
                else:
                    iname = ivars.get(mm.disp or 0, "")
                    if iname:
                        ann = "ivar %s" % iname
                    nv = None
            else:
                if mm.disp in ivars:
                    ann = "ivar? +%#x %s" % (mm.disp, ivars[mm.disp])
    elif m in ("vldr",):
        # vldr sX, [pc, #imm] or [sp..] or [rX]
        try:
            opstr = x.op_str
            ann = "VLD %s" % opstr
            if "[pc" in opstr and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
                pcw = (x.address + 4) & ~3
                eff = (pcw + (ops[1].mem.disp or 0)) & 0xFFFFFFFF
                fv = f32(eff)
                ann = "VLD @%#x = %.4g" % (eff, fv) if fv is not None else "VLD @%#x" % eff
                show = True
            elif "[sp" in opstr:
                show = False
        except Exception:
            pass
    elif m in ("vmov", "vadd", "vmul", "vcvt", "vstr", "vmrs"):
        ann = "VFPU %s" % x.op_str
        show = True
    elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm & ~1
        if t == MSGSEND:
            r1v = regs.get(ARM_REG_R1)
            nm = selval.get(r1v, "?") if r1v is not None else "?"
            ann = "MSGSEND %s r0=%s" % (nm, hex(regs[ARM_REG_R0]) if regs.get(ARM_REG_R0) is not None else "?")
            if nm in ("setPosition:", "labelWithString:fontName:fontSize:",
                      "labelWithString:dimensions:alignment:fontName:fontSize:", "setString:",
                      "contentSize", "position", "setAnchorPoint:", "addChild:", "setColor:",
                      "setToolLabel:", "setScale:", "setScaleX:", "setVisible:", "setOpacity:"):
                show = True
        for r in (ARM_REG_R0, ARM_REG_R1, 2, 3, 12):
            regs.pop(r, None)
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))
        continue
    elif m in ("str", "strb", "strh") and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        base = regs.get(mm.base)
        iname = ivars.get(mm.disp or 0, "")
        if iname and ("toolName" in iname or "activeTool" in iname or "toolMenu" in iname):
            ann = "STORE -> %s" % iname
            show = True
    if dst is not None:
        regs[dst] = nv
    if show or ann:
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))

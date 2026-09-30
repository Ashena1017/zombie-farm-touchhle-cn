"""#4 v4: fully resolve ZFToolsLayer show/hold/hide/setToolLabel + init label creation (sub9).

Key questions:
  (a) which methods call setPosition:/setAnchorPoint:/setContentSize/setTextureRect on toolName?
  (b) where is the toolName CCLabel created (font size? dimensions?)?
  (c) where is the hourglass icon positioned relative to the label?
"""
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


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


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

LAYOUT_SELS = {"setPosition:", "setAnchorPoint:", "setContentSize:", "setTextureRect:",
               "setTextureRect:rotated:untrimmedSize:", "setString:", "setFontSize:",
               "setContentSize:anchor:", "setPosition:anchor:", "convertToNodeSpace:",
               "boundingBox", "contentSize", "position", "anchorPoint",
               "labelWithString:fontName:fontSize:", "labelWithString:dimensions:alignment:fontName:fontSize:",
               "initWithString:dimensions:alignment:fontName:fontSize:",
               "initWithString:fontName:fontSize:", "setDimensions:", "setAlignment:",
               "setLabel:", "setToolLabel:", "addChild:", "addChild:z:", "addChild:z:tag:",
               "setScale:", "setScaleX:", "setScaleY:", "setVisible:",
               "stopAllActions", "runAction:", "setOpacity:", "setColor:"}


def scan(sel):
    imp = methods[sel]
    o = sl.addr_to_file(imp)
    code = sl.data[o:o + 0x4000]
    ins = list(md.disasm(code, imp))
    regs = {}
    print("\n===== %s @ %#x =====" % (sel, imp))
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
            if m == "movt":
                try:
                    import struct as st
                    f = st.unpack("<f", st.pack("<I", nv & 0xFFFFFFFF))[0]
                    if 0.5 <= abs(f) <= 4096:
                        ann = "=%.4g float?" % f
                        show = True
                except Exception:
                    pass
        elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
            dst = ops[0].reg
            nv = regs.get(ops[1].reg)
        elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            nv = ops[-1].imm
            if abs(nv) > 1000 and not (0x2B0000 <= nv <= 0x2C0000 or 0x2D0000 <= nv <= 0x2E0000):
                pass
        elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
                and ops[1].reg == ARM_REG_PC:
            v = regs.get(ops[0].reg)
            if v is not None:
                dst = ops[0].reg
                nv = ((x.address + 4) + v) & 0xFFFFFFFF
                if nv in selref_at:
                    ann = "SELREF " + selref_at[nv]
                    if selref_at[nv] in LAYOUT_SELS or "abel" in selref_at[nv] or "osition" in selref_at[nv]:
                        show = True
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
                        if selref_at[eff] in LAYOUT_SELS:
                            show = True
                    elif v is not None and v in selval:
                        ann = "SEL " + selval[v]
                        if selval[v] in LAYOUT_SELS:
                            show = True
                    elif v is not None:
                        s = cs_(v, 64)
                        if s:
                            ann = "CSTR %r" % s
                            show = True
                        # ivar offset load?
                        if v in ivars and 0xC0 <= v <= 0x130:
                            ann += "  [ivar %s]" % ivars[v]
                            show = True
            else:
                base = regs.get(mm.base)
                if base is not None:
                    eff = (base + (mm.disp or 0)) & 0xFFFFFFFF
                    if eff in selref_at:
                        ann = "SEL " + selref_at[eff]
                        nv = u32(eff)
                        show = True
                    else:
                        iname = ivars.get(mm.disp or 0, "")
                        if iname:
                            ann = "ivar %s" % iname
                            if "toolName" in iname:
                                show = True
                        nv = None
                else:
                    # ldr rD,[r4,#off] where r4=self: ivar load
                    if mm.disp in ivars:
                        ann = "ivar? +%#x %s" % (mm.disp, ivars[mm.disp])
                        if "toolName" in ivars[mm.disp]:
                            show = True
        elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
            t = ops[0].imm & ~1
            if t == MSGSEND:
                r1v = regs.get(ARM_REG_R1)
                nm = selval.get(r1v, "?") if r1v is not None else "?"
                ann = "MSGSEND %s" % nm
                if nm in LAYOUT_SELS:
                    show = True
                    # dump r0-r3 known values
                    ann += "  r0=%s r2=%s r3=%s" % (
                        hex(regs[ARM_REG_R0]) if regs.get(ARM_REG_R0) is not None else "?",
                        hex(regs[2]) if regs.get(2) is not None else "?",
                        hex(regs[3]) if regs.get(3) is not None else "?")
            for r in (ARM_REG_R0, ARM_REG_R1, 2, 3, 12):
                regs.pop(r, None)
            if show or ann.startswith("MSGSEND ?"):
                print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))
            continue
        elif m in ("vmov", "vldr", "vstr", "vmrs", "vadd", "vmul", "vcvt"):
            show = True
        if dst is not None:
            regs[dst] = nv
        if show or ann:
            print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))


for sel in ("showToolName:", "holdToolName:", "hideToolName:", "setToolLabel:"):
    scan(sel)

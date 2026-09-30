"""#4 v3: resolve the two ivar loads + all calls in replaceActiveToolButton: (sub9)."""
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


# selref table
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

# ivar layout of ZFToolsLayer
cb = classes_by_name(sl)
c, info = cb["ZFToolsLayer"]
ivar_list = read_ivars(sl, info.get("ivars"))
ivars = {}
print("ZFToolsLayer ivars:")
for iv in ivar_list:
    ivars[iv["offset"]] = iv["name"]
    print("  +0x%x %s %s" % (iv["offset"], iv.get("type", "?"), iv["name"]))

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
LO, HI = 0xE27E4, 0xE2874
o = sl.addr_to_file(LO)
ins = list(md.disasm(sl.data[o:o + (HI - LO)], LO))
regs = {}
for x in ins:
    if not x.id or not x.operands:
        regs = {}
        continue
    ops = x.operands
    m = x.mnemonic.split(".")[0]
    ann = ""
    dst = None
    nv = None
    if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        nv = imm if m == "movw" else ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF))
    elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
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
                    s = cs_(v, 48)
                    ann = ("CSTR %r" % s) if s else ("@%#x=%#x" % (eff, v))
        else:
            base = regs.get(mm.base)
            if base is not None:
                eff = (base + (mm.disp or 0)) & 0xFFFFFFFF
                if eff in selref_at:
                    ann = "SEL " + selref_at[eff]
                    nv = u32(eff)
                else:
                    iname = ivars.get(mm.disp or 0, "")
                    ann = "ivar? %s +0x%x base=%s" % (iname, mm.disp or 0,
                                                     hex(base) if base is not None else "?")
                    nv = None
    elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm & ~1
        if t == 0x2D014C:
            r1v = regs.get(ARM_REG_R1)
            ann = "MSGSEND %s" % (selval.get(r1v, "?") if r1v is not None else "?")
        else:
            ann = "call %#x" % t
        for r in (ARM_REG_R0, ARM_REG_R1, 2, 3, 12):
            regs.pop(r, None)
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))
        continue
    if dst is not None:
        regs[dst] = nv
    print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))

# class refs for CCLabel etc: dump __objc_classrefs targets
print("\nclassrefs used nearby (search whole method for class names):")
for sec in sl.sections:
    if sec.name != "__objc_classrefs":
        continue
    for off in range(0, sec.size, 4):
        a = sec.addr + off
        v = u32(a)
        if v:
            # class name is at v+8? use cs_ on v
            nm = cs_(v + 8, 64)
            if nm and ("Label" in nm or "Button" in nm or "Sprite" in nm or "Menu" in nm):
                print("  %#x -> %#x %r" % (a, v, nm))

"""#4 v7: proper ARM PIC decode of sub6 toolSelected: head.

ARM idiom here is:
    ldr  r3, [pc, #off]   ; r3 = address of a *slot* S in the literal pool area
    ldr  r1, [pc, #off2]  ; r1 = __objc_selrefs entry address E (points at selector cstring)
    ldr  r0, [pc, r3]     ; r0 = u32(S) -- the thing stored in the slot
    ldr  r1, [pc, r1]     ; r1 = u32(E) = selector cstring address
    ldr  r0, [rX, r0]     ; ivar load using slot value as offset
So the slot S holds either an ivar offset or a classref/selref pointer.
Decode all slots referenced in toolSelected:.
"""
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods, read_ivars
from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 6)


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


# selref table: entry addr -> selector
selref_range = (0x4578E8, 0x45DE04)
sel_of_entry = {}
a = selref_range[0]
while a < selref_range[1]:
    v = u32(a)
    if v:
        t = cs_(v)
        if t and not t.startswith("<addr"):
            sel_of_entry[a] = t
    a += 4

cb = classes_by_name(sl)
names = {}
for cn in ("ZFToolManager", "ZFToolsLayer", "ZFGuiLayer"):
    c, info = cb[cn]
    for iv in read_ivars(sl, info.get("ivars")):
        names.setdefault(iv["offset"], []).append("%s.%s" % (cn, iv["name"]))

c, info = cb["ZFToolManager"]
ms = {m.selector: (m.imp & ~1) for m in all_methods(sl, c, info)}
imp = ms["toolSelected:"]
print("toolSelected: @ %#x" % imp)

md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True
o = sl.addr_to_file(imp)
ins = list(md.disasm(sl.data[o:o + 0x900], imp))

# emulate: track reg -> value; resolve [pc,#..] as slot addresses
regs = {}
for x in ins:
    if not x.id or not x.operands:
        regs = {}
        continue
    ops = x.operands
    m = x.mnemonic
    ann = ""
    show = False
    dst = None
    nv = None
    if m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        dst = ops[0].reg
        if mm.base == ARM_REG_PC and mm.index == 0:
            S = (x.address + 8 + (mm.disp or 0)) & 0xFFFFFFFF
            nv = S
            # what is IN the slot?
            v = u32(S)
            if S in sel_of_entry:
                ann = "E=selref %s" % sel_of_entry[S]
                show = True
            elif v is not None and v in sel_of_entry:
                ann = "S=%#x holds selref E=%#x (%s)" % (S, v, sel_of_entry[v])
                show = True
            elif v is not None and v <= 0x400:
                ann = "S=%#x holds ivar-off %#x %s" % (S, v, names.get(v, ""))
                show = True
            else:
                s = cs_(v, 48) if v else None
                if s:
                    ann = "S=%#x -> CSTR %r" % (S, s)
                    show = True
                elif v is not None:
                    ann = "S=%#x holds %#x" % (S, v)
        elif mm.base == ARM_REG_PC and mm.index != 0:
            idx = regs.get(mm.index)
            base = (x.address + 8) & 0xFFFFFFFF
            if idx is not None:
                eff = (base + idx) & 0xFFFFFFFF
                nv = u32(eff)
                ann = "[pc+rX]: eff=%#x" % eff
                show = True
        else:
            base = regs.get(mm.base)
            if base is not None:
                # base may be a slot address S
                slotval = u32(base)
                eff = (base + (mm.disp or 0)) & 0xFFFFFFFF
                v = u32(eff)
                if base in sel_of_entry:
                    ann = "selref deref?"
                elif slotval is not None and slotval <= 0x400 and base > 0x20000:
                    ann = "ivar? base=S=%#x(off %#x %s)" % (base, slotval, names.get(slotval, ""))
                    show = True
                elif eff in sel_of_entry:
                    ann = "SEL " + sel_of_entry[eff]
                    nv = u32(eff)
                    show = True
                elif v is not None and v in sel_of_entry.values():
                    ann = "@%#x=%#x?" % (eff, v)
                else:
                    s = cs_(v, 48) if v else None
                    if s:
                        ann = "CSTR %r" % s
                        show = True
                nv = None
    elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm & ~1
        if t in (0x393FE0, 0x394004):
            ann = "MSG/struct-ret?"
            show = True
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)
        if show or True:
            pass
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))
        continue
    elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
        dst = ops[0].reg
        nv = regs.get(ops[1].reg)
    elif m == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG:
        b = regs.get(ops[1].reg) if ops[1].type == ARM_OP_REG else None
        if ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            b = (x.address + 8) & 0xFFFFFFFF
        ii = ops[2].imm if ops[2].type == ARM_OP_IMM else regs.get(ops[2].reg)
        if b is not None and ii is not None:
            dst = ops[0].reg
            nv = (b + ii) & 0xFFFFFFFF
            s = cs_(nv, 48)
            if s:
                ann = "CSTR %r" % s
                show = True
    if dst is not None:
        regs[dst] = nv
    if show or ann:
        print("  %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, ann))

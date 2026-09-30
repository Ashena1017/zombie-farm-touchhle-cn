"""#4 v12: trace with ldr-literal resolution to ENTRY (not content), then deref
at the call. Two-level regs: reg -> address-or-immediate. At ldr-literal,
store the EFF address's CONTENT only if eff is not a ref entry; if eff IS a
selref/classref/ivar-slot entry, record the entry addr and resolve later.

Simplest robust approach: reg -> eff-addr when loaded from a literal whose
address is inside a ref section; else reg -> value. At msgsend, resolve:
  r1 -> name via: sel_of[r1] (entry) or name_of_cstr[r1] (cstring) or
          sel_of[u32-entry...]. Also handle r1 = u32(entry) content.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a, limit=100):
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


ref_secs = [s for s in sl.sections if s.name in ("__objc_selrefs", "__objc_classrefs", "__objc_superrefs",
                                                "__objc_ivar", "__data")]
def in_ref(a):
    for s in ref_secs:
        if s.addr <= a < s.addr + s.size:
            return s.name
    return None

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

cb = classes_by_name(sl)
c, info = cb["ZFToolManager"]
ms = {m.selector: (m.imp & ~1) for m in all_methods(sl, c, info)}
START = ms["onTileClickUp:forTool:"]

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
o = sl.addr_to_file(START)
ins = list(md.disasm(sl.data[o:o + 0x6000], START))

def resolve(v):
    if v is None:
        return "?"
    if v in sel_of:
        return sel_of[v] + " (entry)"
    w = u32(v)
    if w is not None and w in name_of_cstr:
        return name_of_cstr[w] + " (via entry %#x)" % v
    if v in name_of_cstr:
        return name_of_cstr[v] + " (direct)"
    return hex(v)

regs = {}
for x in ins:
    if x.address >= 0x26E20:
        break
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
    elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        regs[ops[0].reg] = ops[-1].imm
    elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
            and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if v is not None:
            regs[ops[0].reg] = ((x.address + 4) + v) & 0xFFFFFFFF
    elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        if mm.base == ARM_REG_PC:
            pcw = (x.address + 4) & ~3
            idx = regs.get(mm.index) if mm.index else 0
            if idx is None:
                regs[ops[0].reg] = None
            else:
                eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                if in_ref(eff):
                    regs[ops[0].reg] = u32(eff)  # content of ref entry (sel cstring / class / ivar-off)
                else:
                    regs[ops[0].reg] = u32(eff)
        elif mm.base in regs and regs[mm.base] is not None and not mm.index:
            regs[ops[0].reg] = u32((regs[mm.base] + (mm.disp or 0)) & 0xFFFFFFFF)
        else:
            regs[ops[0].reg] = None
    elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm & ~1
        if t == 0x2D014C and x.address >= 0x26C90:
            print("%#x msgsend r1=%s r0=%s r2=%s r3=%s" % (
                x.address, resolve(regs.get(1)),
                resolve(regs.get(0)), hex(regs[2]) if regs.get(2) is not None else "?",
                hex(regs[3]) if regs.get(3) is not None else "?"))
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)

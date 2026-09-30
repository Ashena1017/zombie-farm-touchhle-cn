"""Reusable annotated disassembler for the ZFR binary.

Usage: python _dis.py <sub 6|9> <start> <end> [ipa]
Resolves the PIC "delta idiom" (ldr rD,[pc,#imm] holding a 32-bit delta, then
ldr rD,[pc,rD]) into __objc_selrefs / __objc_classrefs / cstring targets, and
annotates intra-__text branches with the owning ObjC method.
"""

# --- project root bootstrap (added by _analysis/relocate_paths.py) ----------
import pathlib as _pl
import sys as _sys


def _find_project_root(start):
    for _p in [start, *start.parents]:
        if (_p / "tools" / "audit_zfr_ipa.py").exists():
            return _p
    raise RuntimeError("project root not found above %s" % start)


_PROJECT_ROOT = _find_project_root(_pl.Path(__file__).resolve().parent)
_sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
# ---------------------------------------------------------------------------
import sys, zipfile, struct, bisect, pathlib
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods

IPA = sys.argv[4] if len(sys.argv) > 4 else str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
SUB = int(sys.argv[1], 0)
LO = int(sys.argv[2], 0)
HI = int(sys.argv[3], 0)

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == SUB)
thumb = SUB == 9


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + 300)
    except ValueError:
        return None
    try:
        return sl.data[o:e].decode("utf-8")
    except Exception:
        return None


CS2STR = {}
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
            CS2STR[sec.addr + p] = blob[p:e].decode("utf-8")
        except Exception:
            pass
        p = e + 1

CFSTR = {}
for sec in sl.sections:
    if sec.name not in ("__cfstring", "__objc_cfstring"):
        continue
    for off in range(0, sec.size, 4):
        a = sec.addr + off
        v = u32(a)
        s = CS2STR.get(v) if v else None
        if s:
            CFSTR[a - 8] = s

PTRSEC = {}
for sec in sl.sections:
    if sec.name in ("__objc_selrefs", "__objc_classrefs", "__objc_superrefs"):
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v:
                t = cs_(v)
                if t and not t.startswith("<addr"):
                    PTRSEC[a] = (sec.name, t)

cb = classes_by_name(sl)
full = {}
for cn, (c, info) in cb.items():
    for m in all_methods(sl, c, info):
        if m.imp:
            full.setdefault(m.imp & ~1, []).append(cn + " " + m.selector)
starts = sorted(full)


def owner(a):
    i = bisect.bisect_right(starts, a) - 1
    if i < 0:
        return "?"
    return "%s+%#x" % (full[starts[i]][0], a - starts[i])


txt = next(s for s in sl.sections if s.name == "__text")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
md.detail = True
md.skipdata = True

# ---- pass 1: linear sweep with value tracking, collecting annotations ----
annot = {}
regs = {}
for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
    if not ins.id or not ins.operands:
        regs = {}
        continue
    ops = ins.operands
    m = ins.mnemonic.split(".")[0]
    pc = ins.address + (4 if thumb else 8)
    # `ldr rD,[pc,#imm]` (literal) uses the WORD-ALIGNED base; `add rD,pc` does
    # not.  Two different bases, mixed up before v17.
    pcw = (((ins.address + 4) & ~3) if thumb else pc)
    dst = None
    nv = None
    if m == "add" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and \
            ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
        # ARM   `add rD, pc, rX` -> (addr + 8) + rX
        # Thumb `add rD, pc`     -> (addr + 4) + rD   **NOT word-aligned**
        #   proven statically: at addr%4==2 the unaligned base hits 6629 real
        #   CFString objects, the Align(addr+4,4) base hits 0 (see _v17_pc.py).
        src = ops[2].reg if (not thumb and len(ops) == 3 and
                             ops[2].type == ARM_OP_REG) else ops[0].reg
        v = regs.get(src)
        if v is not None:
            nv = ((ins.address + 4 if thumb else pc) + v) & 0xffffffff
            dst = ops[0].reg
            if nv in CFSTR:
                annot[ins.address] = "CFSTR %r" % CFSTR[nv]
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
            if nv in CFSTR:
                annot[ins.address] = "CFSTR %r" % CFSTR[nv]
    elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        dst = ops[0].reg
        if mm.base == ARM_REG_PC:
            idx = regs.get(mm.index) if mm.index else 0
            if idx is None:
                nv = None
            else:
                eff = (pcw + (mm.disp or 0) + idx) & 0xffffffff
                if eff in PTRSEC:
                    annot[ins.address] = "%s %s" % PTRSEC[eff]
                nv = u32(eff)
                if nv and eff not in PTRSEC:
                    s = cs_(nv)
                    if s and len(s) < 64 and s.isprintable():
                        annot[ins.address] = "CSTR %r" % s
                    else:
                        annot[ins.address] = "@%#x = %#x" % (eff, nv)
        else:
            nv = None
    elif m in ("movw", "movt") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xffff
        nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xffff)) if m == "movt" else imm
    elif m == "mov" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
        s = cs_(nv) if nv else None
        if s and len(s) < 64 and s.isprintable():
            annot.setdefault(ins.address, "CSTR %r" % s)
    elif m in ("bl", "blx", "b"):
        if ops[0].type == ARM_OP_IMM and not (txt.addr <= ops[0].imm < txt.addr + txt.size):
            for r in (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12):
                regs.pop(r, None)
        dst = None
    else:
        dst = None
    if dst is not None:
        regs[dst] = nv
    if m in ("bl", "blx") and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm & ~1
        if txt.addr <= t < txt.addr + txt.size:
            annot[ins.address] = "-> %s" % owner(t)

# ---- pass 2: print the requested range ----
o = sl.addr_to_file(LO)
if o is None:
    print("LO %#x not mapped" % LO)
    raise SystemExit(1)
print("==== sub%d  %#x..%#x ====" % (SUB, LO, HI))
for ins in md.disasm(sl.data[o:o + (HI - LO)], LO):
    raw = u32(ins.address)
    print("  %#010x  %-8s %-42s %s" % (ins.address, ins.mnemonic, ins.op_str, annot.get(ins.address, "")))

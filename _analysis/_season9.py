"""Annotated view: resolve selref/literal targets with the proven delta-idiom tracker."""

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
import sys, zipfile, struct, bisect
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
RANGE = (int(sys.argv[1], 0), int(sys.argv[2], 0)) if len(sys.argv) > 2 else (0x16d3f8, 0x16d570)


def make(sub):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9

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
    annot = {}
    regs = {}
    for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if not ins.id or not ins.operands:
            continue
        ops = ins.operands
        m = ins.mnemonic.split(".")[0]
        pc = ins.address + (4 if thumb else 8)
        dst = None
        nv = None
        if m == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG:
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
                if nv in selrefs:
                    annot[ins.address] = "SEL %s" % selrefs[nv]
                else:
                    s = cs_(nv)
                    if s and len(s) < 60 and s.isprintable():
                        annot[ins.address] = "CSTR %r" % s
                    elif nv:
                        annot[ins.address] = "&%#x" % nv
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
                    if eff in selrefs:
                        annot[ins.address] = "SEL %s" % selrefs[eff]
                    else:
                        s = cs_(nv) if nv else None
                        if s and len(s) < 60 and s.isprintable():
                            annot[ins.address] = "CSTR %r" % s
                        elif nv:
                            annot[ins.address] = "@%#x = %#x" % (eff, nv)
            else:
                nv = None
        elif m in ("mov", "movw", "movt") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            nv = ops[-1].imm
            s = cs_(nv) if nv else None
            if s and len(s) < 60 and s.isprintable() and not m == "movt":
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
    return sl, md, annot, owner


for sub in (6, 9):
    sl, md, annot, owner = make(sub)
    lo, hi = (RANGE if sub == 6 else (RANGE[0] - 0x60200 * 0, RANGE[1]))
    print("\n############ sub%d  %#x..%#x ############" % (sub, lo, hi))
    o = sl.addr_to_file(lo)
    for ins in md.disasm(sl.data[o:o + (hi - lo)], lo):
        print("  %#08x: %-8s %-40s %s" % (ins.address, ins.mnemonic, ins.op_str, annot.get(ins.address, "")))

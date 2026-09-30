"""Find objc_msgSend sites using the selector 'getRandomAbilityToUnlock' or
'localizedStringForKey:value:table:', and the sites referencing the CFString
'Unlocked a new %@ ability!'.  Value-tracking with the delta idiom."""

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
SELS = ("getRandomAbilityToUnlock", "localizedStringForKey:value:table:", "stringWithFormat:",
        "abilityName", "setAbilityName:")
CFSTRS = {"Unlocked a new %@ ability!"}

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
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
            e = sl.data.index(b"\0", o, o + 400)
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

    # CFString object -> string
    cfmap = {}
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
    for sec in sl.sections:
        if sec.name not in ("__cfstring", "__objc_cfstring"):
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            s = cs2str.get(v) if v else None
            if s in CFSTRS:
                cfmap[a - 8] = s
    print("\n########## sub%d  cfstrings: %s" % (sub, {hex(k): v for k, v in cfmap.items()}))

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
    regs = {}
    for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if not ins.id or not ins.operands:
            regs = {}
            continue
        ops = ins.operands
        m = ins.mnemonic.split(".")[0]
        pc = ins.address + (4 if thumb else 8)
        dst = None
        nv = None
        tag = None
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
                if nv in cfmap:
                    tag = "CFSTR %r" % cfmap[nv]
        elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            dst = ops[0].reg
            if mm.base == ARM_REG_PC:
                idx = regs.get(mm.index) if mm.index else 0
                if idx is None:
                    nv = None
                else:
                    eff = (pc + (mm.disp or 0) + idx) & 0xffffffff
                    if eff in selrefs:
                        tag = "SEL %s" % selrefs[eff]
                    nv = u32(eff)
            else:
                nv = None
        elif m in ("mov", "movw", "movt") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            nv = ops[-1].imm
        elif m in ("bl", "blx", "b"):
            if ops[0].type == ARM_OP_IMM and not (txt.addr <= ops[0].imm < txt.addr + txt.size):
                for r in (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12):
                    regs.pop(r, None)
            dst = None
        else:
            dst = None
        if tag:
            print("   %#010x  %-8s %-34s %s   (%s)" % (ins.address, m, ins.op_str, tag, owner(ins.address)))
        if dst is not None:
            regs[dst] = nv
        if m in ("bl", "blx") and ops[0].type == ARM_OP_IMM:
            t = ops[0].imm & ~1
            if txt.addr <= t < txt.addr + txt.size:
                for r in ("r1", "r2", "r3"):
                    rr = {"r1": ARM_REG_R1, "r2": ARM_REG_R2, "r3": ARM_REG_R3}[r]
                    pass
        # report msgSend sites whose selector register is known
        if m in ("bl", "blx") and ops[0].type == ARM_OP_IMM:
            t = ops[0].imm & ~1
            if t in (0x393FE0 if not thumb else 0x2D014C,) or True:
                for rr, nm in ((ARM_REG_R1, "r1"), (ARM_REG_R2, "r2"), (ARM_REG_R3, "r3")):
                    v = regs.get(rr)
                    if v is not None and v in selrefs and selrefs[v] in SELS:
                        print("   %#010x  MSG %-34s %s   (%s)" % (ins.address, selrefs[v], nm, owner(ins.address)))
                        break

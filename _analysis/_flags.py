"""Where is GameData.abilityFlags read/written, and what does the caller of
-getRandomAbilityToUnlock do?"""

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

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v13fix.ipa")
WANT = ("abilityFlags", "setAbilityFlags:", "getRandomAbilityToUnlock",
        "abilitiesToUnlockForTier:", "flagBit", "newAbilityIconClicked:")

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 6)


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
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True
print("=== every objc_msgSend site using the selectors of interest ===")
regs = {}
for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
    if not ins.id or not ins.operands:
        regs = {}
        continue
    ops = ins.operands
    m = ins.mnemonic
    dst = None
    nv = None
    if m == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG:
        a = b = None
        for k, oo in ((1, ops[1]), (2, ops[2])):
            if oo.type == ARM_OP_REG and oo.reg == ARM_REG_PC:
                v = ins.address + 8
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
    elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        dst = ops[0].reg
        if mm.base == ARM_REG_PC:
            idx = regs.get(mm.index) if mm.index else 0
            if idx is None:
                nv = None
            else:
                eff = (ins.address + 8 + (mm.disp or 0) + idx) & 0xffffffff
                if eff in selrefs:
                    print("   SEL %-32s @ %#010x  %s" % (selrefs[eff], ins.address, owner(ins.address)))
                nv = u32(eff)
        else:
            nv = None
    elif m in ("mov", "movw", "movt") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        nv = ops[-1].imm
    elif m in ("bl", "blx", "b"):
        for r in (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12):
            regs.pop(r, None)
        dst = None
    else:
        dst = None
    if dst is not None:
        regs[dst] = nv

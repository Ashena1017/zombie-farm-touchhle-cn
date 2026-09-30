"""Locate the two stringWithFormat: sites inside sub9 -getRandomAbilityToUnlock
that consume the CFString 'Unlocked a new %@ ability!' (object 0x3a85d0)."""

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

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
TARGET_CF = 0x3A85D0
LO, HI = 0x85ca0, 0x86e00

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)


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

txt = next(s for s in sl.sections if s.name == "__text")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

o = sl.addr_to_file(LO)
insns = list(md.disasm(sl.data[o:o + (HI - LO)], LO))
print("disassembled %d instructions in %#x..%#x" % (len(insns), LO, HI))

# find where the CFString object address is computed (movw/movt pair, then add rX,pc)
hits = []
regs = {}
for i, ins in enumerate(insns):
    ops = ins.operands if ins.id else []
    m = ins.mnemonic
    if m == "movw" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        regs[ops[0].reg] = ops[-1].imm & 0xFFFF
    elif m == "movt" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        lo = regs.get(ops[0].reg) or 0
        regs[ops[0].reg] = ((ops[-1].imm & 0xFFFF) << 16) | (lo & 0xFFFF)
    elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
        lo = regs.get(ops[0].reg)
        if lo is not None:
            eff = (ins.address + 4 + lo) & 0xFFFFFFFF
            if eff == TARGET_CF:
                hits.append(i)
                print("   %#010x  add %s, pc  => %#x  (CFString)" % (ins.address, ins.op_str, eff))
        regs[ops[0].reg] = None
    elif m in ("bl", "blx"):
        regs = {}
    elif ops and ops[0].type == ARM_OP_REG:
        regs[ops[0].reg] = None

# context around each hit
for i in hits:
    print("\n===== context @ %#010x =====" % insns[i].address)
    for j in range(max(0, i - 8), min(len(insns), i + 30)):
        ins = insns[j]
        cmt = ""
        ops = ins.operands if ins.id else []
        if ins.mnemonic in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
            cmt = "-> %#x" % (ops[0].imm & ~1)
        print("   %#010x  %-9s %s   %s" % (ins.address, ins.mnemonic, ins.op_str, cmt))

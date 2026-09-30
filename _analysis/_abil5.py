"""In sub9 -getRandomAbilityToUnlock, find every site that materialises one of the
ability-name CFStrings and report the destination register.  This proves which
register carries the raw ability name at the stringWithFormat: call sites.
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
import sys, zipfile, struct
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
NAMES = {"Zombie", "Girl Zombie", "ZomBumpkin", "Headless Zombie", "Garden Zombie", "Zyborg",
         "ZomBeauty", "ZomBruiser", "Kindlehead", "ZomBotanist", "Zombot", "Amazombie",
         "ZomBrute", "Flamehead", "Flower Zombie", "ZomGoblin", "Robo Zombie", "Zombielocks",
         "Zombarian", "Party Zombie", "Zombee", "Imp Zombie", "zombie"}
LO, HI = 0x85ca0, 0x86e00

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")


def cs_(sl, a):
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


for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

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
    CF = {}
    for sec in sl.sections:
        if sec.name not in ("__cfstring", "__objc_cfstring"):
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            s = CS2STR.get(v) if v else None
            if s in NAMES:
                CF[a - 8] = s

    rng = (0xb70f8, 0xb8500) if sub == 6 else (LO, HI)
    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if sub == 9 else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    o = sl.addr_to_file(rng[0])
    print("\n########## sub%d  %#x..%#x   name-CFStrings=%d" % (sub, rng[0], rng[1], len(CF)))
    regs = {}
    for ins in md.disasm(sl.data[o:o + (rng[1] - rng[0])], rng[0]):
        ops = ins.operands if ins.id else []
        m = ins.mnemonic
        pc = ins.address + (4 if sub == 9 else 8)
        if m == "movw" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ops[-1].imm & 0xFFFF
        elif m == "movt" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ((ops[-1].imm & 0xFFFF) << 16) | ((regs.get(ops[0].reg) or 0) & 0xFFFF)
        elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            v = regs.get(ops[0].reg)
            if v is not None and ((ins.address + (4 if sub == 9 else 8) + v) & 0xFFFFFFFF) in CF:
                eff = (ins.address + (4 if sub == 9 else 8) + v) & 0xFFFFFFFF
                print("   %#010x  add %-12s -> %-18r" % (ins.address, ins.op_str, CF[eff]))
            regs[ops[0].reg] = None
        elif m in ("ldr",) and len(ops) == 2 and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
            lit = ins.address + (4 if sub == 9 else 8) + (ops[1].mem.disp or 0)
            v = u32(lit)
            regs[ops[0].reg] = v
            if v is not None and v in CF:
                print("   %#010x  ldr %-12s -> %-18r  (literal %#x)" % (ins.address, ins.op_str, CF[v], lit))
        elif m == "b" and ops and ops[0].type == ARM_OP_IMM:
            pass
        elif ops and ops[0].type == ARM_OP_REG:
            regs[ops[0].reg] = None

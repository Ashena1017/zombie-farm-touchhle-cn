"""What does -[ZFFightMan newAbilityIconClicked:] do with abilityFlags, and what is
the class that implements hasFlag: ?"""

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
from inspect_v3_facts import classes_by_name, all_methods

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v13fix.ipa")
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
    cb = classes_by_name(sl)
    print("\n########## sub%d" % sub)
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.selector in ("hasFlag:", "setFlag:", "clearFlag:", "abilityFlags",
                              "newAbilityIconClicked:", "flagBit"):
                print("   %-6s %-24s %-28s imp=%s" %
                      ("class" if m.kind == "class" else "inst", cn, m.selector,
                       hex(m.imp) if m.imp else None))

# dump newAbilityIconClicked: around the abilityFlags read (sub6 0xb9084)
sl = next(s for s in parse_fat(fat) if s.subtype == 6)


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None else struct.unpack_from("<I", sl.data, o)[0]


selrefs = {}
for sec in sl.sections:
    if sec.name != "__objc_selrefs":
        continue
    for off in range(0, sec.size, 4):
        a = sec.addr + off
        v = u32(a)
        if v:
            t = cs_(sl, v)
            if t and not t.startswith("<addr"):
                selrefs[a] = t

print("\n=== sub6 ZFFightMan -newAbilityIconClicked: 0xb8f80..0xb9120 ===")
o = sl.addr_to_file(0xB8F80)
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True
regs = {}
for ins in md.disasm(sl.data[o:o + (0xB9120 - 0xB8F80)], 0xB8F80):
    cmt = ""
    ops = ins.operands if ins.id else []
    if ins.mnemonic == "ldr" and len(ops) == 2 and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
        idx = regs.get(ops[1].mem.index) if ops[1].mem.index else 0
        if idx is not None:
            eff = (ins.address + 8 + (ops[1].mem.disp or 0) + idx) & 0xffffffff
            if eff in selrefs:
                cmt = "; SEL %s" % selrefs[eff]
    print("   %#010x  %-9s %-38s %s" % (ins.address, ins.mnemonic, ins.op_str, cmt))
    if ins.mnemonic == "ldr" and len(ops) == 2 and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
        idx = regs.get(ops[1].mem.index) if ops[1].mem.index else 0
        if idx is not None:
            eff = (ins.address + 8 + (ops[1].mem.disp or 0) + idx) & 0xffffffff
            regs[ops[0].reg] = u32(eff)
            continue
    if ops and ops[0].type == ARM_OP_REG:
        regs[ops[0].reg] = None

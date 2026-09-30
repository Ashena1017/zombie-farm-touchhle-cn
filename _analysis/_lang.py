"""What is -getCurrentLanguage, and which branch of the popup does the game take?"""

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
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")


def cs_(sl, a):
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


for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    cb = classes_by_name(sl)
    print("\n########## sub%d" % sub)
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.selector and ("CurrentLanguage" in m.selector or "currentLanguage" in m.selector
                               or "preferredLanguage" in m.selector or "language" == m.selector.lower()):
                print("   %-6s %-28s %-26s imp=%s" %
                      ("class" if m.kind == "class" else "inst", cn, m.selector,
                       hex(m.imp) if m.imp else None))

# receiver class of the getCurrentLanguage call in getRandomAbilityToUnlock (sub6 0xb74a4/0xb74ac)
sl = next(s for s in parse_fat(fat) if s.subtype == 6)


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


print("\n=== resolving the receiver of getCurrentLanguage at 0xb74b0 ===")
for lit in (0xB74A0 + 8 + 0xEF8, 0xB74A4 + 8 + 0xEF8):
    d = u32(lit)
    cons = lit - 8 - 0xEF8
    eff = (cons + 8 + d) & 0xFFFFFFFF
    print("   literal@%#x = %#x -> slot %#x" % (lit, d, eff))
    v = u32(eff)
    print("      slot value = %#x" % (v or 0))
    if v:
        for sec in sl.sections:
            if sec.addr <= v < sec.addr + sec.size:
                print("      -> in %s" % sec.name)
        # classref -> class_t -> name
        data = u32(v + 16)
        name_ptr = u32(data + 16) if data else None
        print("      class_ro=%s name=%r" % (hex(data) if data else None,
                                              cs_(sl, name_ptr) if name_ptr else None))

# dump the language chain in detail with correct selref resolution
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

md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True
print("\n=== 0xb74a0..0xb7540 annotated ===")
o = sl.addr_to_file(0xB74A0)
regs = {}
for ins in md.disasm(sl.data[o:o + 0xA0], 0xB74A0):
    cmt = ""
    ops = ins.operands
    if ins.mnemonic == "ldr" and len(ops) == 2 and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
        idx = regs.get(ops[1].mem.index) if ops[1].mem.index else 0
        if idx is not None:
            eff = (ins.address + 8 + (ops[1].mem.disp or 0) + idx) & 0xFFFFFFFF
            if eff in selrefs:
                cmt = "; SEL %s" % selrefs[eff]
            else:
                cmt = "; *%#x = %#x" % (eff, u32(eff) or 0)
            regs[ops[0].reg] = u32(eff)
            print("   %#010x  %-8s %-34s %s" % (ins.address, ins.mnemonic, ins.op_str, cmt))
            continue
        else:
            lit = ins.address + 8 + (ops[1].mem.disp or 0)
            cmt = "; lit@%#x = %#x" % (lit, u32(lit) or 0)
    print("   %#010x  %-8s %-34s %s" % (ins.address, ins.mnemonic, ins.op_str, cmt))
    if ops and ops[0].type == ARM_OP_REG:
        regs[ops[0].reg] = None

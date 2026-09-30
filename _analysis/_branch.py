"""Precisely annotate both branches of the ability popup and inspect the fonts."""

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
import sys, zipfile, struct, re
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v13fix.ipa")
z = zipfile.ZipFile(IPA)
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
        e = sl.data.index(b"\0", o, o + 400)
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

md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True
for lo, hi, label in ((0xB7530, 0xB7660, "CJK branch"),
                      (0xB7654, 0xB7770, "default branch")):
    print("\n===== %s  %#x..%#x =====" % (label, lo, hi))
    o = sl.addr_to_file(lo)
    regs = {}
    for ins in md.disasm(sl.data[o:o + (hi - lo)], lo):
        cmt = ""
        ops = ins.operands
        if ins.mnemonic == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG:
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
                nv = (a + b) & 0xFFFFFFFF
                regs[ops[0].reg] = nv
                if nv in CFSTR:
                    cmt = "CFSTR %r" % CFSTR[nv]
        elif ins.mnemonic == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            if mm.base == ARM_REG_PC:
                idx = regs.get(mm.index) if mm.index else 0
                if idx is not None:
                    eff = (ins.address + 8 + (mm.disp or 0) + idx) & 0xFFFFFFFF
                    if eff in PTRSEC:
                        cmt = "%s %s" % PTRSEC[eff]
                    regs[ops[0].reg] = u32(eff)
                else:
                    lit = ins.address + 8 + (mm.disp or 0)
                    cmt = "@%#x = %#x" % (lit, u32(lit) or 0)
                    regs[ops[0].reg] = u32(lit)
            else:
                regs[ops[0].reg] = None
        elif ins.mnemonic in ("mov", "movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ops[-1].imm
        print("   %#010x  %-8s %-36s %s" % (ins.address, ins.mnemonic, ins.op_str, cmt))

print("\n===== fonts present in the bundle =====")
for n in sorted(z.namelist()):
    b = n.rsplit("/", 1)[-1].lower()
    if b.endswith(".fnt") or b.endswith(".ttf") or b.endswith(".otf"):
        print("   %-46s %d bytes" % (n.rsplit("/", 1)[-1], z.getinfo(n).file_size))

print("\n===== char map of ABD26.fnt =====")
cand = [n for n in z.namelist() if n.lower().endswith("abd26.fnt")]
if cand:
    d = z.read(cand[0])
    txt = d.decode("utf-8", "replace")
    chars = re.findall(r"char id=(\d+)", txt)
    ids = sorted(int(c) for c in chars)
    print("   %s: %d glyphs, id range %d..%d" % (cand[0], len(ids), ids[0], ids[-1]))
    print("   has any id > 0x2000 (CJK)? %s" % any(i > 0x2000 for i in ids))
    print("   max id = %d (%r)" % (ids[-1], chr(ids[-1])))
    print("   sample ids: %s" % ids[:20])
else:
    print("   ABD26.fnt not found")

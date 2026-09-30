
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
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 6)


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    e = sl.data.index(b"\0", o)
    return sl.data[o:e].decode("utf-8", "replace")


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
ivars = {}
for sec in sl.sections:
    if sec.name in ("__objc_ivar", "__objc_ivar_data", "__data"):
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v is not None and a in selrefs:
                pass

md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True


def dump(addr, n, label):
    print("\n=== %s @ %#08x ===" % (label, addr))
    o = sl.addr_to_file(addr)
    regs = {}
    for ins in md.disasm(sl.data[o:o + n * 4], addr):
        cmt = ""
        ops = ins.operands
        if ins.mnemonic == "ldr" and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            pc = ins.address + 8
            if mm.base == ARM_REG_PC:
                idx = regs.get(mm.index) if mm.index else 0
                if idx is None:
                    idx = 0
                eff = (pc + (mm.disp or 0) + idx) & 0xffffffff
                if eff in selrefs:
                    cmt = "  ; SEL %r" % selrefs[eff]
                else:
                    v = u32(eff)
                    if v is not None and (v & 0xff000000) in (0x2e000000, 0x31000000, 0x30000000, 0x2f000000, 0x32000000):
                        cmt = "  ; delta %#x" % v
                    elif v is not None:
                        s = cs_(v)
                        if s and len(s) < 40 and all(32 <= ord(c) < 127 for c in s):
                            cmt = "  ; CSTR %r" % s
                        else:
                            cmt = "  ; lit %#x" % v
        if ins.mnemonic in ("ldr", "mov", "add") and ops and ops[0].type == ARM_OP_REG:
            regs[ops[0].reg] = None
        print("  %#08x: %-8s %-42s%s" % (ins.address, ins.mnemonic, ins.op_str, cmt))


dump(0x16d3dc, 8, "ZFQuestMan checkSeason")
dump(0x16d3f8, 60, "next method (addSeasonalQuests?)")
dump(0x16c328, 60, "addQuestWithID: +0x378 region")

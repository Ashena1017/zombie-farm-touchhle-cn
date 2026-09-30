"""Find likely-dead method bodies in __text (candidate code caves).

A method is a dead candidate when:
  * no `bl`/`b` in the slice targets its imp, AND
  * its selector never appears in __objc_selrefs (so nobody can msgSend it), AND
  * it is not a category/class method of a class that overrides a super method
    we cannot see -- so we additionally require the selector to be absent from
    __objc_methname of the OTHER slice's selector usage ... (we keep it simple:
    report and inspect by hand).
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
import sys, zipfile, struct, bisect
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods

IPA = sys.argv[1] if len(sys.argv) > 1 else str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
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
            e = sl.data.index(b"\0", o, o + 300)
        except ValueError:
            return None
        try:
            return sl.data[o:e].decode("utf-8")
        except Exception:
            return None

    selrefs = set()
    for sec in sl.sections:
        if sec.name != "__objc_selrefs":
            continue
        for off in range(0, sec.size, 4):
            v = u32(sec.addr + off)
            if v:
                t = cs_(v)
                if t:
                    selrefs.add(t)

    cb = classes_by_name(sl)
    meths = []          # (imp_aligned, class, selector, size_guess)
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.imp:
                meths.append((m.imp & ~1, cn, m.selector))
    meths.sort()
    impset = {}
    for i, (a, cn, sel) in enumerate(meths):
        end = meths[i + 1][0] if i + 1 < len(meths) else None
        impset[a] = (cn, sel, end)

    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    bl_targets = set()
    for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if not ins.id or not ins.operands:
            continue
        if ins.mnemonic in ("bl", "blx", "b") and ins.operands[0].type == ARM_OP_IMM:
            t = ins.operands[0].imm & ~1
            if txt.addr <= t < txt.addr + txt.size:
                bl_targets.add(t)

    print("\n########## sub%d : methods=%d  bl_targets=%d" % (sub, len(meths), len(bl_targets)))
    out = []
    for a, (cn, sel, end) in sorted(impset.items()):
        if a in bl_targets:
            continue
        if sel in selrefs:
            continue
        size = (end - a) if end else None
        out.append((size or 0, a, cn, sel))
    out.sort(reverse=True)
    for size, a, cn, sel in out[:60]:
        print("   size=%-6d %#010x  %s  %s" % (size, a, cn, sel))

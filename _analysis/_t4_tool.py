"""#4 diagnostics: dump ZFToolsLayer layout methods with selector annotations (sub9 live slice)."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
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
        e = sl.data.index(b"\0", o, o + 200)
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
c, info = cb["ZFToolsLayer"]
methods = {m.selector: (m.imp & ~1) for m in all_methods(sl, c, info)}
for sel in ("setToolLabel:", "replaceActiveToolButton:", "toggleTool:withButtonImageName:withToolName:",
            "showToolName:", "hideActiveToolButton", "unhideActiveToolButton"):
    print("%-45s @ %#x" % (sel, methods.get(sel, 0)))

# float immediates of interest: movt rX,#0x41XX patterns decode
def f32_of(movt_imm):
    return struct.unpack("<f", struct.pack("<I", 0x40000000 | (movt_imm << 16)))[0]

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

WANT_METHODS = ("setToolLabel:", "replaceActiveToolButton:",
                "toggleTool:withButtonImageName:withToolName:")
for sel in WANT_METHODS:
    imp = methods[sel]
    print("\n===== sub9 ZFToolsLayer %s @ %#x =====" % (sel, imp))
    o = sl.addr_to_file(imp)
    code = sl.data[o:o + 0x3000]
    ins = list(md.disasm(code, imp))
    regs = {}
    for i, x in enumerate(ins):
        if not x.id or not x.operands:
            regs = {}
            continue
        ops = x.operands
        mnem = x.mnemonic.split(".")[0]
        cmt = ""
        # track movw/movt pairs for float decode
        if mnem in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            imm = ops[-1].imm & 0xFFFF
            if mnem == "movw":
                regs[dst] = imm
            else:
                lo = regs.get(dst, 0) & 0xFFFF
                full = (imm << 16) | lo
                regs[dst] = full
                try:
                    f = struct.unpack("<f", struct.pack("<I", full))[0]
                    cmt = "full=%#x float?=%s" % (full, f)
                except Exception:
                    cmt = "full=%#x" % full
            print("  %#010x  %-8s %-38s %s" % (x.address, x.mnemonic, x.op_str, cmt))
            continue
        if mnem == "mov" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ops[-1].imm
        pcw = (x.address + 4) & ~3
        if mnem == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
            idx = regs.get(ops[1].mem.index) if ops[1].mem.index else 0
            if idx is not None:
                eff = (pcw + (ops[1].mem.disp or 0) + idx) & 0xFFFFFFFF
                if eff in selrefs:
                    cmt = "SEL " + selrefs[eff]
                nv = u32(eff)
                regs[ops[0].reg] = nv
                if nv and eff not in selrefs:
                    s = cs_(nv)
                    if s and len(s) < 80 and s.isprintable():
                        cmt = "CSTR %r" % s
                    else:
                        cmt = "@%#x = %#x" % (eff, nv)
            print("  %#010x  %-8s %-38s %s" % (x.address, x.mnemonic, x.op_str, cmt))
            continue
        if mnem in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
            print("  %#010x  %-8s %-38s %s" % (x.address, x.mnemonic, x.op_str, "CALL sub(%#x)" % (ops[0].imm & ~1)))
            # clear volatile regs incl. movt tracking of r0-r3,r12
            for r in list(regs):
                regs.pop(r, None)
            continue
        if mnem in ("pop", "b", "bx", "cbz", "cbnz"):
            if mnem == "pop":
                pass
            print("  %#010x  %-8s %-38s %s" % (x.address, x.mnemonic, x.op_str, cmt))
            continue
        # print float-ish consts: vmov.f32, movs with big imm handled by capstone comment
        if "s1" in x.op_str or "s0" in x.op_str or x.mnemonic.startswith("vmov") or \
                x.mnemonic.startswith("vstr") or x.mnemonic.startswith("vldr") or \
                mnem in ("adds", "subs", "add", "sub", "str", "ldr"):
            print("  %#010x  %-8s %-38s %s" % (x.address, x.mnemonic, x.op_str, cmt))

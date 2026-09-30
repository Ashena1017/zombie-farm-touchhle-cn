"""Dump every `stringWithFormat:` call site inside a given method (sub6 or sub9),
with a few instructions of context, so the sub9 twins of the sub6 patch sites can
be identified even when the CFString materialisation idiom differs."""
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,  # noqa: E402
                                ARM_REG_PC)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"
WANT = [("ZFMarketMenu", "alertWindow:dismissedPositive:"),
        ("ZFToolManager", "onTileClickUp:forTool:"),
        ("ZFToolManager", "toolSelected:")]

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9

    def u32(a):
        o = sl.addr_to_file(a)
        import struct
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
        import struct
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v:
                t = cs_(v)
                if t and not t.startswith("<addr"):
                    selrefs[a] = t

    cb = classes_by_name(sl)
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if (cn, m.selector) not in WANT or not m.imp:
                continue
            imp = m.imp & ~1
            print("\n=== sub%d  %s -%s  @ %#x ===" % (sub, cn, m.selector, imp))
            o = sl.addr_to_file(imp)
            md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
            md.detail = True
            md.skipdata = True
            ins = list(md.disasm(sl.data[o:o + 0x4000], imp))
            regs = {}
            last_fmt = None
            for i, x in enumerate(ins):
                ops = x.operands if x.id else []
                if not ops:
                    regs = {}
                    continue
                mnem = x.mnemonic.split(".")[0]
                pc = x.address + (4 if thumb else 8)
                cmt = ""
                if mnem == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                        ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
                    idx = regs.get(ops[1].mem.index) if ops[1].mem.index else 0
                    if idx is not None:
                        eff = (pc + (ops[1].mem.disp or 0) + idx) & 0xFFFFFFFF
                        if eff in selrefs:
                            cmt = "SEL %s" % selrefs[eff]
                            if selrefs[eff] == "stringWithFormat:":
                                last_fmt = x.address
                            regs[ops[0].reg] = u32(eff)
                            if cmt:
                                print("   %#010x  %-8s %-40s %s" % (x.address, x.mnemonic, x.op_str, cmt))
                            continue
                if mnem in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
                    t = ops[0].imm & ~1
                    if last_fmt is not None and abs(x.address - last_fmt) <= 8:
                        print("   %#010x  %-8s %-40s  <== stringWithFormat: CALL"
                              % (x.address, x.mnemonic, x.op_str))
                        # print the 6 instructions before it
                        for y in ins[max(0, i - 6):i]:
                            print("        %#010x  %-8s %s" % (y.address, y.mnemonic, y.op_str))
                        print("        ---")
                        last_fmt = None
                if ops and ops[0].type == ARM_OP_REG:
                    regs[ops[0].reg] = None

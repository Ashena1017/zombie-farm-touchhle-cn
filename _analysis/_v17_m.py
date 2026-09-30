"""v17 recon B: dump a named method in BOTH slices, with every CFString it
materialises decoded (so we can see the real message text)."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
WANT = sys.argv[1:] or ["ZFMarketMenu -alertWindow:dismissedPositive:"]

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")


def cstr(sl, a):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + 300)
    except ValueError:
        return None
    return sl.data[o:e].decode("utf-8", "replace")


for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    cb = classes_by_name(sl)
    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    for cn, (c, info) in sorted(cb.items()):
        for m in all_methods(sl, c, info):
            key = "%s %s" % (cn, m.selector)
            if not any(w.lower() in key.lower() for w in WANT):
                continue
            if not m.imp:
                continue
            print("\n" + "=" * 78)
            print("sub%d  %s   imp=%#x" % (sub, key, m.imp))
            print("=" * 78)
            a = m.imp & ~1
            o = sl.addr_to_file(a)
            if o is None:
                print("   <no file offset>")
                continue
            regs = {}
            for ins in md.disasm(sl.data[o:o + 0x400], a):
                note = ""
                ops = ins.operands
                mm = ins.mnemonic.split(".")[0]
                # decode any register that now holds a CFString / cstring addr
                for r, v in list(regs.items()):
                    pass
                if mm == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                        ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
                    pc = ins.address + (4 if thumb else 8)
                    idx = regs.get(ops[1].mem.index) if ops[1].mem.index else 0
                    if idx is not None:
                        eff = (pc + (ops[1].mem.disp or 0) + idx) & 0xFFFFFFFF
                        v = u32(eff)
                        regs[ops[0].reg] = v
                        if v is not None and 0x2f0000 <= v <= 0x350000:
                            t = cstr(sl, v)
                            if t:
                                note = "  ; = %r" % t
                elif mm == "add" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and \
                        ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
                    src = ops[2].reg if (not thumb and len(ops) == 3
                                         and ops[2].type == ARM_OP_REG) else ops[0].reg
                    v = regs.get(src)
                    if v is not None:
                        nv = ((((ins.address + 4) & ~3) + v) if thumb else (pc + v)) & 0xFFFFFFFF
                        # CFString object?
                        fo = sl.addr_to_file(nv)
                        if fo is not None and fo + 16 <= len(sl.data):
                            isa, flags, data, size = struct.unpack_from("<IIII", sl.data, fo)
                            if flags == 0x7C8:
                                note = "  ; CFSTR %#x = %r" % (nv, cstr(sl, data))
                        if not note:
                            t = cstr(sl, nv)
                            if t and len(t) < 80:
                                note = "  ; %r" % t
                        regs[ops[0].reg] = nv
                elif mm in ("movw", "movt") and ops and ops[0].type == ARM_OP_REG:
                    d = ops[0].reg
                    imm = ops[-1].imm & 0xFFFF
                    regs[d] = ((imm << 16) | ((regs.get(d) or 0) & 0xFFFF)) if mm == "movt" else imm
                elif mm == "mov" and ops and ops[0].type == ARM_OP_REG:
                    if len(ops) >= 2 and ops[-1].type == ARM_OP_REG:
                        regs[ops[0].reg] = regs.get(ops[-1].reg)
                    elif len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
                        regs[ops[0].reg] = ops[-1].imm
                elif mm in ("bl", "blx", "b"):
                    if ops[0].type == ARM_OP_IMM:
                        tgt = ops[0].imm
                        nm = None
                        for cn2, (c2, info2) in cb.items():
                            for m2 in all_methods(sl, c2, info2):
                                if m2.imp and (m2.imp & ~1) == (tgt & ~1):
                                    nm = "%s %s" % (cn2, m2.selector)
                        if nm:
                            note = "  -> %s" % nm
                    for r in (0, 1, 2, 3, 12):
                        regs.pop(r, None)
                print("   %#010x  %-42s%s" % (ins.address, ins.mnemonic + " " + ins.op_str, note))

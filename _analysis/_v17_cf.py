"""v17 recon A: enumerate EVERY CFString whose text matches a filter, then report
every code site that materialises it (ARM ldr/add-pc and Thumb movw/movt/add-pc).

Usage:  python _v17_cf.py <ipa> <filter> [<filter> ...]
"""
import bisect
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
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,  # noqa: E402
                                ARM_REG_PC)

IPA = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
FILTERS = sys.argv[2:] or ["Used"]


def read_cstr(sl, a):
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


with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

print("IPA: %s" % IPA.name)
print("filters: %r" % (FILTERS,))

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    OBJC = 0x2D014C if thumb else 0x393FE0

    # ---- 1. enumerate CFString objects -------------------------------------
    objs = {}          # object addr -> text
    for sec in sl.sections:
        o = sec.offset
        end = o + sec.size - 16
        while o <= end:
            isa, flags = struct.unpack_from("<II", sl.data, o)
            if flags == 0x7C8:
                data, size = struct.unpack_from("<II", sl.data, o + 8)
                t = read_cstr(sl, data)
                if t is not None and abs(size - len(t.encode("utf-8"))) <= 2:
                    objs[sec.addr + (o - sec.offset)] = t
                o += 16
            else:
                o += 4

    hits = {a: t for a, t in objs.items() if any(f in t for f in FILTERS)}
    print("\n" + "#" * 78)
    print("# sub%d : %d CFStrings total, %d match" % (sub, len(objs), len(hits)))
    print("#" * 78)
    for a, t in sorted(hits.items()):
        o = sl.addr_to_file(a)
        data, size = struct.unpack_from("<II", sl.data, o + 8)
        print("   %#010x  size=%-3d data=%#010x  %r" % (a, size, data, t))

    # ---- 2. walk every method, track register values -----------------------
    cb = classes_by_name(sl)
    full = {}
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append(cn + " " + m.selector)
    starts = sorted(full)

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        return "%s+%#x" % (full[starts[i]][0], a - starts[i]) if i >= 0 else "?"

    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    bounds = sorted(set(starts) | {txt.addr, txt.addr + txt.size})
    ins_list = []
    for lo, hi in zip(bounds, bounds[1:]):
        if not (txt.addr <= lo < txt.addr + txt.size):
            continue
        o = sl.addr_to_file(lo)
        if o is None:
            continue
        for x in md.disasm(sl.data[o:o + min(hi - lo, 0x20000)], lo):
            ins_list.append(x)

    print("\n   -- code references (%d instructions) --" % len(ins_list))
    regs = {}
    for i, ins in enumerate(ins_list):
        if not ins.id or not ins.operands:
            regs = {}
            continue
        ops = ins.operands
        m = ins.mnemonic.split(".")[0]
        pc = ins.address + (4 if thumb else 8)
        pcw = (((ins.address + 4) & ~3) if thumb else pc)   # literal-load base
        dst = nv = hit = None

        if m == "add" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and \
                ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            src = ops[2].reg if (not thumb and len(ops) == 3
                                 and ops[2].type == ARM_OP_REG) else ops[0].reg
            v = regs.get(src)
            if v is not None:
                # Thumb `add rD, pc` base is addr+4, NOT word-aligned (proven in
                # _v17_pc.py: 6629 hits unaligned vs 0 aligned at addr%4==2).
                nv = (((ins.address + 4) if thumb else pc) + v) & 0xFFFFFFFF
                dst = ops[0].reg
                hit = hits.get(nv)
        elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_MEM:
            mm = ops[1].mem
            dst = ops[0].reg
            if mm.base == ARM_REG_PC:
                idx = regs.get(mm.index) if mm.index else 0
                if idx is not None:
                    eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                    nv = u32(eff)
                    hit = hits.get(eff) or (hits.get(nv) if nv is not None else None)
        elif m in ("movw", "movt") and ops[0].type == ARM_OP_REG and \
                len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            imm = ops[-1].imm & 0xFFFF
            nv = ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF)) if m == "movt" else imm
            hit = hits.get(nv)
        elif m == "mov" and ops[0].type == ARM_OP_REG and \
                len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            nv = ops[-1].imm
            hit = hits.get(nv)
        elif m in ("bl", "blx", "b"):
            if ops[0].type == ARM_OP_IMM and not (txt.addr <= ops[0].imm < txt.addr + txt.size):
                for r in (0, 1, 2, 3, 12):
                    regs.pop(r, None)
        else:
            dst = None

        if hit:
            print("   %#010x  r%-2d <- %r" % (ins.address, dst, hit))
            print("        %-14s %s" % (owner(ins.address), ins.mnemonic + " " + ins.op_str))
            for j in range(i + 1, min(i + 14, len(ins_list))):
                k = ins_list[j]
                if k.mnemonic in ("bl", "blx") and k.operands and \
                        k.operands[0].type == ARM_OP_IMM and \
                        (k.operands[0].imm & ~1) == OBJC:
                    print("        -> objc_msgSend @ %#010x  %s"
                          % (k.address, owner(k.address)))
                    break
        if dst is not None:
            regs[dst] = nv

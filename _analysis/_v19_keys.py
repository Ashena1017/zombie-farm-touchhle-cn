"""v19 recon D: for a set of Localizable keys, find the CFString in sub9, find who
materialises it, and dump the surrounding code with selref/CFString annotation so
the label's fontSize / setColor: can be read off.
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
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC  # noqa: E402
import plistlib  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v18fix.ipa"
KEYS = sys.argv[1:] or ["Mausoleum", "Power", "Health", "Speed"]

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
    zh = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))

sl = next(s for s in parse_fat(fat) if s.subtype == 9)
txt = next(s for s in sl.sections if s.name == "__text")


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cstr(a, limit=300):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    e = sl.data.find(b"\0", o, o + limit)
    if e < 0:
        return None
    try:
        return sl.data[o:e].decode("utf-8")
    except Exception:
        return None


CS2STR = {}
sec = next(s for s in sl.sections if s.name == "__cstring")
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
PTRSEC = {}
csec = next(s for s in sl.sections if s.name == "__cfstring")
for off in range(0, csec.size - 16, 16):
    v = u32(csec.addr + off + 8)
    if v in CS2STR and u32(csec.addr + off + 4) == 0x7C8:
        CFSTR[csec.addr + off] = CS2STR[v]
for sn in ("__objc_selrefs", "__objc_classrefs", "__objc_superrefs"):
    s2 = next((s for s in sl.sections if s.name == sn), None)
    if not s2:
        continue
    for off in range(0, s2.size, 4):
        v = u32(s2.addr + off)
        t = CS2STR.get(v) if v else None
        if t:
            PTRSEC[s2.addr + off] = (sn, t)

cb = classes_by_name(sl)
full = {}
for cn, (c, info) in cb.items():
    for m in all_methods(sl, c, info):
        if m.imp:
            full.setdefault(m.imp & ~1, []).append("%s %s" % (cn, m.selector))
starts = sorted(full)


def owner(a):
    i = bisect.bisect_right(starts, a) - 1
    return "%s+%#x" % (full[starts[i]][0], a - starts[i]) if i >= 0 else "?"


TARGETS = {a: t for a, t in CFSTR.items() if t in KEYS}
print("== CFStrings for %r ==" % (KEYS,))
for a, t in sorted(TARGETS.items()):
    print("   %#010x  %r   zh-Hans=%r" % (a, t, zh.get(t, "<none>")))

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
bounds = sorted(set(starts) | {txt.addr, txt.addr + txt.size})
ins = []
for lo, hi in zip(bounds, bounds[1:]):
    if not (txt.addr <= lo < txt.addr + txt.size):
        continue
    o = sl.addr_to_file(lo)
    if o is None:
        continue
    for x in md.disasm(sl.data[o:o + min(hi - lo, 0x20000)], lo):
        ins.append(x)

idx = {x.address: i for i, x in enumerate(ins)}
regs = {}
hits = []
for i, x in enumerate(ins):
    if not x.id or not x.operands:
        regs = {}
        continue
    ops = x.operands
    mm = x.mnemonic.split(".")[0]
    for r in (12,):
        pass
    if mm in ("movw", "movt") and ops and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        d = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        regs[d] = ((imm << 16) | ((regs.get(d) or 0) & 0xFFFF)) if mm == "movt" else imm
    elif mm == "mov" and ops and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        regs[ops[0].reg] = ops[-1].imm
    elif mm == "add" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and \
            ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
        d = ops[0].reg
        v = regs.get(d)
        if v is not None:
            nv = ((x.address + 4) + v) & 0xFFFFFFFF
            regs[d] = nv
            if nv in TARGETS:
                hits.append((x.address, TARGETS[nv]))
    elif mm == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
            ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
        eff = ((x.address + 4) & ~3) + (ops[1].mem.disp or 0)
        v = u32(eff)
        regs[ops[0].reg] = v
        if eff in TARGETS:
            hits.append((x.address, TARGETS[eff]))
    elif mm in ("bl", "blx", "b"):
        for r in (0, 1, 2, 3, 12):
            regs.pop(r, None)

for addr, name in hits:
    print("\n" + "=" * 74)
    print("%r  materialised @ %#x   (%s)" % (name, addr, owner(addr)))
    print("=" * 74)
    i = idx[addr]
    for x in ins[max(0, i - 34):i + 22]:
        note = ""
        ops = x.operands
        mm = x.mnemonic.split(".")[0]
        if mm == "add" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and \
                len(ops) >= 2 and ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
            v = None
            note = ""
        if mm == "ldr" and len(ops) == 2 and ops[1].type == ARM_OP_MEM and \
                ops[1].mem.base == ARM_REG_PC:
            eff = ((x.address + 4) & ~3) + (ops[1].mem.disp or 0)
            if eff in PTRSEC:
                note = PTRSEC[eff][1]
            else:
                v = u32(eff)
                if v in CFSTR:
                    note = "CFSTR %r" % CFSTR[v]
        if mm in ("movw", "movt") and ops and ops[-1].type == ARM_OP_IMM:
            imm = ops[-1].imm & 0xFFFF
            if mm == "movt" and imm in (0x4120, 0x4140, 0x4160, 0x4180, 0x4190,
                                        0x41a0, 0x41c0, 0x4200, 0x4208, 0x41f0):
                note = "float %g" % struct.unpack("<f", struct.pack("<I", imm << 16))[0]
        if mm in ("bl", "blx") and ops[0].type == ARM_OP_IMM:
            t = ops[0].imm & ~1
            note = ("-> " + owner(t)) if txt.addr <= t < txt.addr + txt.size else "-> %#x" % t
        print("   %#010x  %-44s %s" % (x.address, x.mnemonic + " " + x.op_str, note))

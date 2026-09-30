"""v19 recon C: find the storage-item panel's TITLE and BODY label constructions.

Strategy: locate the Localizable key whose Chinese value is the description text,
then find which CFString in the executable carries that key and who materialises
it.  The label call right after is the body; the other label in the same method
is the title.
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
SUB = 9

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
    zh = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))

print("== zh-Hans values containing 作用于 / 长成 / 道具 ==")
for k, v in zh.items():
    if any(s in v for s in ("作用于", "长成", "该道具")):
        print("   %-70r -> %r" % (k, v))

sl = next(s for s in parse_fat(fat) if s.subtype == SUB)
txt = next(s for s in sl.sections if s.name == "__text")


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


cf = {}
sec = next(s for s in sl.sections if s.name == "__cfstring")
for off in range(0, sec.size - 16, 16):
    if struct.unpack_from("<I", sl.data, sec.offset + off + 4)[0] != 0x7C8:
        continue
    data, size = struct.unpack_from("<II", sl.data, sec.offset + off + 8)
    t = cstr(data)
    if t:
        cf[sec.addr + off] = t


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


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


import sys as _s
NEEDLES = _s.argv[1:] or ["Works on", "grow a zombie"]
WANT = {a: t for a, t in cf.items() if any(n.lower() in t.lower() for n in NEEDLES)}
print("\n== CFStrings matching %r ==" % (NEEDLES,))
for a, t in sorted(WANT.items()):
    print("   %#010x  %r" % (a, t))

# disassemble the whole ZFAlertWindowStorageItem method and report label calls
TARGET_CLS = "ZFAlertWindowStorageItem"
for cn, (c, info) in cb.items():
    if cn != TARGET_CLS:
        continue
    for m in all_methods(sl, c, info):
        if not m.imp or "alertWindowSlideInInformative" not in m.selector:
            continue
        a = m.imp & ~1
        o = sl.addr_to_file(a)
        print("\n== %s -%s @ %#x ==" % (cn, m.selector[:60], a))
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        md.detail = True
        md.skipdata = True
        regs = {}
        ins = list(md.disasm(sl.data[o:o + 0x4000], a))
        for i, x in enumerate(ins):
            ops = x.operands
            mm = x.mnemonic.split(".")[0]
            note = ""
            if not x.id:
                regs = {}
                continue
            if mm in ("movw", "movt") and ops and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
                d = ops[0].reg
                imm = ops[-1].imm & 0xFFFF
                nv = ((imm << 16) | ((regs.get(d) or 0) & 0xFFFF)) if mm == "movt" else imm
                regs[d] = nv
                if mm == "movt" and 0x4100 <= (nv >> 16) <= 0x4250:
                    f = struct.unpack("<f", struct.pack("<I", nv))[0]
                    if 8.0 <= f <= 60.0:
                        note = "  ; float %g" % f
            elif mm == "mov" and ops and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
                regs[ops[0].reg] = ops[-1].imm
            elif mm == "add" and len(ops) >= 2 and ops[0].type == ARM_OP_REG and \
                    ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
                src = ops[0].reg
                v = regs.get(src)
                if v is not None:
                    nv = ((x.address + 4) + v) & 0xFFFFFFFF
                    regs[ops[0].reg] = nv
                    if nv in WANT:
                        note = "  ; CFSTR %r" % WANT[nv]
            elif mm == "bl" or mm == "blx":
                if ops[0].type == ARM_OP_IMM:
                    t = ops[0].imm & ~1
                    if txt.addr <= t < txt.addr + txt.size:
                        note = "  -> %s" % owner(t)
                    else:
                        note = "  -> %#x" % t
                for r in (0, 1, 2, 3, 12):
                    regs.pop(r, None)
            if note or (mm in ("bl", "blx")):
                print("   %#010x  %-44s%s" % (x.address, x.mnemonic + " " + x.op_str, note))

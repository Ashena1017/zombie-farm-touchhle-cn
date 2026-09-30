"""#4 v9: find setToolLabel: callers via PIC-aware scan (sub9 live slice).

Strategy: linear disasm of __text with movw/movt/add-pc/ldr-literal tracking.
Record every blx objc_msgSend site where tracked r1 == selref entry whose
content derefs to the 'setToolLabel:' cstring.  Print the 30 insns before each
hit so the format-string feeding r2 can be identified.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC,
                                ARM_REG_R0, ARM_REG_R1)

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
txt = next(s for s in sl.sections if s.name == "__text")


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a, limit=160):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + limit)
    except ValueError:
        return None
    try:
        s = sl.data[o:e].decode("utf-8")
    except Exception:
        return None
    return s if s and s.isprintable() else None


# entry addr -> selector. NOTE: __objc_selrefs entries point DIRECTLY at the
# selector cstring (u32(entry) == cstring vaddr). There is no second table.
sel_of = {}
for sec in sl.sections:
    if sec.name != "__objc_selrefs":
        continue
    for off in range(0, sec.size, 4):
        a = sec.addr + off
        v = u32(a)
        if v:
            t = cs_(v)
            if t and not t.startswith("<addr"):
                sel_of[a] = t

SETTOOL_ENTRY = next(a for a, t in sel_of.items() if t == "setToolLabel:")
SETTOOL_PTR = u32(SETTOOL_ENTRY)  # the selector cstring address; callers load THIS into r1
print("setToolLabel: selref entry = %#x -> cstring @ %#x" % (SETTOOL_ENTRY, SETTOOL_PTR))

MSGSEND = 0x2D014C
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
ins = list(md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr))

regs = {}
hist = []  # (addr, text)
hits = []
for x in ins:
    line = "%#010x  %-8s %s" % (x.address, x.mnemonic, x.op_str)
    if not x.id or not x.operands:
        regs = {}
        hist.append((x.address, line))
        if len(hist) > 60:
            hist.pop(0)
        continue
    ops = x.operands
    m = x.mnemonic.split(".")[0]
    if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
        dst = ops[0].reg
        imm = ops[-1].imm & 0xFFFF
        regs[dst] = imm if m == "movw" else ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF))
    elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
        regs[ops[0].reg] = regs.get(ops[1].reg)
    elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
        regs[ops[0].reg] = ops[-1].imm
    elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
            and ops[1].reg == ARM_REG_PC:
        v = regs.get(ops[0].reg)
        if v is not None:
            regs[ops[0].reg] = ((x.address + 4) + v) & 0xFFFFFFFF
    elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
        mm = ops[1].mem
        if mm.base == ARM_REG_PC:
            pcw = (x.address + 4) & ~3
            idx = regs.get(mm.index) if mm.index else 0
            if idx is not None:
                regs[ops[0].reg] = u32((pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF)
            else:
                regs[ops[0].reg] = None
        else:
            regs[ops[0].reg] = None
    elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
        t = ops[0].imm & ~1
        if t == MSGSEND and regs.get(ARM_REG_R1) == SETTOOL_PTR:
            hits.append((x.address, list(hist)))
        for r in (ARM_REG_R0, ARM_REG_R1, 2, 3, 12):
            regs.pop(r, None)
    hist.append((x.address, line))
    if len(hist) > 60:
        hist.pop(0)

print("hits: %d" % len(hits))

# CFString table for format identification
csec = next(s for s in sl.sections if s.name == "__cstring")
blob = sl.data[csec.offset:csec.offset + csec.size]
cstr_at = {}
p = 0
while p < len(blob):
    e = blob.find(b"\0", p)
    if e < 0:
        break
    try:
        cstr_at[csec.addr + p] = blob[p:e].decode("utf-8")
    except Exception:
        pass
    p = e + 1
cfstr = {}
for sec in sl.sections:
    if sec.name != "__cfstring":
        continue
    for off in range(0, sec.size, 16):
        a = sec.addr + off
        data = u32(a + 8)
        if data is not None and data in cstr_at:
            cfstr[a] = cstr_at[data]

for addr, ctx in hits:
    print("\n##### setToolLabel: call @ %#x #####" % addr)
    for _, ln in ctx[-34:]:
        print("   " + ln)
    print("   %#010x  blx      objc_msgSend   <<<<" % addr)

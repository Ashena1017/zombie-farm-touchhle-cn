"""#4 v8: who calls -setToolLabel: (both slices) + where does its format string come from.

The red-box text comes from ZFToolManager -toolSelected: -> [toolsLayer setToolLabel:].
Find ALL callers of setToolLabel: and check whether each passes the SAME
'%@ (%i)        ' format (sub9 0x212d0) or something else.
Then figure out how the label width/icon layout works: the label is a CCLabel
child of ZFToolsLayer; find setPosition:/contentSize readers near setToolLabel:.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

SHORT6, LONG6 = 0x3BE1D4, 0x3BE64F
SHORT9, LONG9 = 0x2FA1D4, 0x2FA64F

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    SHORT, LONG = (SHORT6, LONG6) if sub == 6 else (SHORT9, LONG9)

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    def cs_(a, limit=120):
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

    # selref entry addr -> selector
    sel_entry = {}
    for sec in sl.sections:
        if sec.name != "__objc_selrefs":
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v:
                t = cs_(v)
                if t and not t.startswith("<addr"):
                    sel_entry[a] = t
    sel_val = {}
    for sec in sl.sections:
        if sec.name != "__objc_selrefs":
            continue
        for off in range(0, sec.size, 4):
            a = sec.addr + off
            v = u32(a)
            if v and a in sel_entry:
                sel_val[v] = sel_entry[a]

    # CFString object addr -> string
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

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    txt = next(s for s in sl.sections if s.name == "__text")
    code = sl.data[txt.offset:txt.offset + txt.size]
    insns = list(md.disasm(code, txt.addr))

    # find all bl/blx to objc_msgSend (sub9 0x2d014c; sub6 0x393fe0) with r1 == setToolLabel:
    MSGSEND = 0x2D014C if sub == 9 else 0x393FE0
    regs = {}

    def track(x):
        ops = x.operands
        m = x.mnemonic.split(".")[0]
        dst = None
        nv = None
        if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            imm = ops[-1].imm & 0xFFFF
            nv = imm if m == "movw" else ((imm << 16) | ((regs.get(dst) or 0) & 0xFFFF))
        elif not thumb and m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC and ops[1].mem.index == 0:
            S = (x.address + 8 + (ops[1].mem.disp or 0)) & 0xFFFFFFFF
            dst = ops[0].reg
            nv = u32(S)
        elif not thumb and m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC and ops[1].mem.index != 0:
            idx = regs.get(ops[1].mem.index)
            if idx is not None:
                eff = (x.address + 8 + idx) & 0xFFFFFFFF
                dst = ops[0].reg
                nv = u32(eff)
        elif thumb and m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and \
                ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
            pcw = (x.address + 4) & ~3
            idx = regs.get(ops[1].mem.index) if ops[1].mem.index else 0
            if idx is not None:
                eff = (pcw + (ops[1].mem.disp or 0) + idx) & 0xFFFFFFFF
                dst = ops[0].reg
                nv = u32(eff)
        elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
            dst = ops[0].reg
            nv = regs.get(ops[1].reg)
        elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
                and ops[1].reg == ARM_REG_PC and thumb:
            v = regs.get(ops[0].reg)
            if v is not None:
                dst = ops[0].reg
                nv = ((x.address + 4) + v) & 0xFFFFFFFF
        elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and len(ops) >= 2 and ops[-1].type == ARM_OP_IMM:
            dst = ops[0].reg
            nv = ops[-1].imm
        if dst is not None:
            regs[dst] = nv

    print("=== sub%d: callers of setToolLabel: ===" % sub)
    for i, x in enumerate(insns):
        if not x.id or not x.operands:
            if not x.id:
                regs = {}
            continue
        ops = x.operands
        m = x.mnemonic.split(".")[0]
        if m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM and (ops[0].imm & ~1) == MSGSEND:
            if regs.get(1) is not None and sel_val.get(regs[1]) == "setToolLabel:":
                # look back for the stringWithFormat: call feeding r2 (r0=the NSString)
                print("  setToolLabel: call @ %#x" % x.address)
                for y in insns[max(0, i - 40):i]:
                    ym = y.mnemonic.split(".")[0]
                    if ym in ("bl", "blx") and y.operands and y.operands[0].type == ARM_OP_IMM and \
                            (y.operands[0].imm & ~1) == MSGSEND and regs.get(1) is not None:
                        pass
                # print context
                for y in insns[max(0, i - 14):i + 1]:
                    extra = ""
                    if y.operands and y.operands[0].type == ARM_OP_REG:
                        rv = regs.get(y.operands[0].reg)
                    print("     %#010x  %-8s %s" % (y.address, y.mnemonic, y.op_str))
            track(x)
        else:
            track(x)


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
IPA=str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v6.ipa")
with zipfile.ZipFile(IPA) as z: fat=z.read("Payload/ZFR.app/ZFR")
WANT=("addUserData:","readUserData:intoGameData:withVersion:","saveGameDataToBinaryFile:asFriend:",
      "writeToFile:","writeToFileInNeighbors:","dataWithData:")
for sub in (6,9):
    sl=next(s for s in parse_fat(fat) if s.subtype==sub)
    thumb=sub==9
    def u32(a):
        o=sl.addr_to_file(a); return None if o is None else struct.unpack_from("<I",sl.data,o)[0]
    def cs_(a):
        o=sl.addr_to_file(a)
        if o is None: return None
        e=sl.data.index(b"\0",o); return sl.data[o:e].decode("utf-8","replace")
    slots={}
    for sec in sl.sections:
        if sec.name!="__objc_selrefs": continue
        for off in range(0,sec.size,4):
            a=sec.addr+off; v=u32(a)
            if v is None: continue
            s=cs_(v)
            if s in WANT: slots[a]=s
    cb=classes_by_name(sl); full={}
    for cn,(c,info) in cb.items():
        for m in all_methods(sl,c,info):
            if m.imp: full.setdefault(m.imp & ~1, []).append(cn+" "+m.selector)
    starts=sorted(full)
    txt=next(s for s in sl.sections if s.name=="__text")
    md=Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM); md.detail=True; md.skipdata=True
    print("\n########## sub%d thumb=%s  slots=%s" % (sub,thumb,{hex(k):v for k,v in slots.items()}))
    off=txt.offset
    regs={}
    for ins in md.disasm(sl.data[off:off+txt.size], txt.addr):
        if not ins.id or not ins.operands: continue
        ops=ins.operands; m=ins.mnemonic.split(".")[0]; pc=ins.address+(4 if thumb else 8)
        dst=None; nv=None
        if m=="add" and len(ops)==3 and ops[0].type==ARM_OP_REG:
            a=b=None
            for k,o in ((1,ops[1]),(2,ops[2])):
                if o.type==ARM_OP_REG and o.reg==ARM_REG_PC: v=pc
                elif o.type==ARM_OP_REG: v=regs.get(o.reg)
                elif o.type==ARM_OP_IMM: v=o.imm
                else: v=None
                if k==1: a=v
                else: b=v
            if a is not None and b is not None:
                nv=(a+b)&0xffffffff; dst=ops[0].reg
                if nv in slots:
                    i=bisect.bisect_right(starts,ins.address)-1
                    print("   SELREF %-40s @ %#010x  %s" % (slots[nv], ins.address, full[starts[i]][0]+"+%#x"%(ins.address-starts[i]) if i>=0 else "?"))
        elif m=="ldr" and len(ops)==2 and ops[0].type==ARM_OP_REG and ops[1].type==ARM_OP_MEM:
            mm=ops[1].mem; dst=ops[0].reg
            if mm.base==ARM_REG_PC:
                idx=regs.get(mm.index) if mm.index else 0
                if idx is None: nv=None
                else:
                    eff=(pc+mm.disp+idx)&0xffffffff
                    if eff in slots:
                        i=bisect.bisect_right(starts,ins.address)-1
                        print("   SELREF %-40s @ %#010x  %s" % (slots[eff], ins.address, full[starts[i]][0]+"+%#x"%(ins.address-starts[i]) if i>=0 else "?"))
                    o2=sl.addr_to_file(eff); nv=struct.unpack_from("<I",sl.data,o2)[0] if o2 is not None else None
            else: nv=None
        elif m in ("mov","movw","movt") and ops[0].type==ARM_OP_REG and len(ops)>=2 and ops[-1].type==ARM_OP_IMM:
            dst=ops[0].reg; nv=ops[-1].imm
        elif m in ("bl","blx","b"):
            if ops[0].type==ARM_OP_IMM and not (txt.addr<=ops[0].imm<txt.addr+txt.size):
                for r in (ARM_REG_R0,ARM_REG_R1,ARM_REG_R2,ARM_REG_R3,ARM_REG_R12): regs.pop(r,None)
            dst=None
        else: dst=None
        if dst is not None: regs[dst]=nv

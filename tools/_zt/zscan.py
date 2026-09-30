"""Per-method msgSend selector scanner with PC-relative selref tracking."""
import struct
import zt
import zsel
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from capstone.arm_const import (ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_OP_FP,
                                ARM_REG_PC)


class Ctx:
    def __init__(self, sl):
        self.sl = sl
        self.thumb = sl.subtype == 9
        self.stubs = zsel.stub_map(sl)
        self.selrefs = zsel.selref_map(sl)
        self.classrefs = zsel.classref_map(sl)
        self.rows = zsel.owner_map(sl)
        self.text = next(s for s in sl.sections if s.name == '__text')
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if self.thumb else CS_MODE_ARM)
        md.detail = True
        self.md = md

    def md_nodata(self):
        return self.md

    def owner(self, a):
        return zsel.owner_of(self.rows, a)

    def meth_end(self, start, cap=0x1000):
        nxt = None
        for s, _, _, _ in self.rows:
            if s > start:
                nxt = s
                break
        return min(nxt, start + cap) if nxt else start + cap


def word(sl, addr):
    off = sl.addr_to_file(addr)
    if off is None or off + 4 > len(sl.data):
        return None
    return struct.unpack_from('<I', sl.data, off)[0]


def scan_method(ctx, start, end, verbose=False):
    """Symbolically track reg <- selref/imm/float; report msgSend call sites.

    Returns (events, lines). events: dict with 'calls' list of
    (addr, callee, selector, argsnapshot).
    """
    sl = ctx.sl
    regs = {}       # reg -> ('sel', text) | ('imm', v) | ('cls', name) | ('pcbase', v)
    fregs = {}      # sN -> float
    stack = {}      # sp offset -> value tuple
    calls = []
    lines = []
    pending_movw = {}
    rdef = {}       # reg -> [addrs that built the current value]
    sdef = {}       # sp disp -> [addrs]
    fdefs = {}      # sN -> [addrs]

    def setdef(reg, *srcs):
        acc = []
        for s in srcs:
            acc += rdef.get(s, [])
        rdef[reg] = acc

    for i in _iter_resync(ctx, start, end):
        mn = i.mnemonic
        ops = i.operands
        txt = f'{i.address:#08x}: {i.bytes.hex():<8} {mn:<10} {i.op_str}'

        def rd(r):
            return regs.get(r)

        # --- movw/movt pair -> 32-bit imm ---
        if (mn in ('movw', 'mov', 'mov.w') and len(ops) == 3
                and ops[1].type == ARM_OP_IMM and ops[2].type == ARM_OP_IMM):
            # ARM 'mov rD, #imm8, #rot' -- capstone splits the modified-immediate
            # into imm8 + explicit ROR amount whenever the encoding is not the
            # canonical one for that value.  Must fold it, or the value is lost.
            i8 = ops[1].imm & 0xFFFFFFFF
            rot = ops[2].imm & 31
            v = ((i8 >> rot) | (i8 << (32 - rot))) & 0xFFFFFFFF if rot else i8
            regs[ops[0].reg] = ('imm', v)
            rdef[ops[0].reg] = [i.address]
        elif mn in ('movw', 'mov') and len(ops) == 2 and ops[1].type == ARM_OP_IMM:
            regs[ops[0].reg] = ('imm', ops[1].imm & 0xFFFF if mn == 'movw' else ops[1].imm)
            rdef[ops[0].reg] = [i.address]
        elif mn == 'movt' and len(ops) == 2 and ops[1].type == ARM_OP_IMM:
            prev = regs.get(ops[0].reg)
            base = prev[1] if prev and prev[0] == 'imm' else 0
            regs[ops[0].reg] = ('imm', (base & 0xFFFF) | ((ops[1].imm & 0xFFFF) << 16))
            rdef[ops[0].reg] = rdef.get(ops[0].reg, []) + [i.address]
        elif mn == 'orr' and len(ops) == 3 and ops[2].type == ARM_OP_IMM:
            prev = regs.get(ops[1].reg)
            if prev and prev[0] == 'imm':
                regs[ops[0].reg] = ('imm', prev[1] | ops[2].imm)
                rdef[ops[0].reg] = rdef.get(ops[1].reg, []) + [i.address]
        # --- add rX, pc  => resolve PC-relative ---
        elif mn in ('add', 'add.w', 'addw') and len(ops) >= 2:
            dst = ops[0].reg
            srcs = [o for o in ops[1:] if o.type == ARM_OP_REG]
            spsrc = next((o for o in srcs if i.reg_name(o.reg) == 'sp'), None)
            if spsrc is not None and len(ops) == 3 and ops[2].type == ARM_OP_IMM:
                # add rX, sp, #imm  -> rX is a *stack pointer alias*.  Needed for
                # the stm.w rX,{...} arg-marshalling idiom in the Thumb slice.
                regs[dst] = ('spoff', ops[2].imm)
                rdef[dst] = [i.address]
            elif any(o.reg == ARM_REG_PC for o in srcs):
                other = next((o for o in srcs if o.reg != ARM_REG_PC), None)
                v = regs.get(other.reg) if other else regs.get(dst)
                if v and v[0] == 'imm':
                    # ADD (register) reading PC: value is instr_addr+4 (Thumb) /
                    # +8 (ARM), NOT word-aligned. Alignment applies only to
                    # ADR / LDR(literal).
                    pcb = i.address + (4 if ctx.thumb else 8)
                    regs[dst] = ('addr', (pcb + v[1]) & 0xFFFFFFFF)
                else:
                    regs.pop(dst, None)
            else:
                regs.pop(dst, None)
        # --- ldr rX, [pc, #imm] literal pool ---
        elif mn.startswith('ldr') and len(ops) == 2 and ops[1].type == ARM_OP_MEM:
            m = ops[1].mem
            dst = ops[0].reg
            if m.base == ARM_REG_PC and m.index == 0:
                pcb = (i.address + (4 if ctx.thumb else 8)) & (~3 if ctx.thumb else ~0)
                lit = word(sl, pcb + m.disp)
                if lit is not None:
                    if (pcb + m.disp) in ctx.selrefs:
                        regs[dst] = ('sel', ctx.selrefs[pcb + m.disp])
                    elif lit in ctx.selrefs:
                        regs[dst] = ('sel', ctx.selrefs[lit])
                    elif lit in ctx.classrefs:
                        regs[dst] = ('cls', ctx.classrefs[lit])
                    else:
                        regs[dst] = ('imm', lit)
                else:
                    regs.pop(dst, None)
            elif m.base == ARM_REG_PC and m.index != 0:
                # ARM slice idiom: ldr rX,[pc,rY]  (rY holds a pool-computed disp)
                iv = regs.get(m.index)
                if iv and iv[0] == 'imm':
                    pcb = i.address + (4 if ctx.thumb else 8)
                    a = (pcb + iv[1]) & 0xFFFFFFFF
                    if a in ctx.selrefs:
                        regs[dst] = ('sel', ctx.selrefs[a])
                    elif a in ctx.classrefs:
                        regs[dst] = ('cls', ctx.classrefs[a])
                    else:
                        v = word(sl, a)
                        if v is not None and v in ctx.selrefs:
                            regs[dst] = ('sel', ctx.selrefs[v])
                        elif v is not None:
                            regs[dst] = ('imm', v)
                        else:
                            regs.pop(dst, None)
                else:
                    regs.pop(dst, None)
            else:
                # ldr rX,[rY] where rY is a resolved selref/classref slot addr
                base = regs.get(m.base)
                if base and base[0] == 'addr' and m.index == 0:
                    a = base[1] + m.disp
                    if a in ctx.selrefs:
                        regs[dst] = ('sel', ctx.selrefs[a])
                    elif a in ctx.classrefs:
                        regs[dst] = ('cls', ctx.classrefs[a])
                    else:
                        v = word(sl, a)
                        regs[dst] = ('imm', v) if v is not None else None
                        if regs.get(dst) is None:
                            regs.pop(dst, None)
                else:
                    regs.pop(dst, None)
        # --- mov reg,reg ---
        elif mn in ('mov', 'mov.w', 'movs') and len(ops) == 2 and ops[1].type == ARM_OP_REG:
            v = regs.get(ops[1].reg)
            if v:
                regs[ops[0].reg] = v
            else:
                regs.pop(ops[0].reg, None)
            setdef(ops[0].reg, ops[1].reg)
        # --- VFP immediate / vcvt ---
        elif mn.startswith('vmov') and len(ops) == 2 and ops[1].type == ARM_OP_FP:
            fregs[i.reg_name(ops[0].reg)] = ops[1].fp
            fdefs[i.reg_name(ops[0].reg)] = [i.address]
        elif mn.startswith('vcvt'):
            fregs[i.reg_name(ops[0].reg)] = 'vcvt'
            fdefs[i.reg_name(ops[0].reg)] = [i.address]
        # --- stores to stack (arg slots) ---
        elif mn.startswith('str') or mn.startswith('vstr') or mn.startswith('stm'):
            if ops and ops[-1].type == ARM_OP_MEM and not mn.startswith('stm'):
                m = ops[-1].mem
                # base may be sp itself, or a register holding 'add rX,sp,#imm'
                bv = regs.get(m.base)
                sbase = None
                if i.reg_name(m.base) == 'sp':
                    sbase = 0
                elif bv and bv[0] == 'spoff':
                    sbase = bv[1]
                if sbase is not None and m.index == 0:
                    d = sbase + m.disp
                    src = ops[0]
                    if mn.startswith('vstr'):
                        stack[d] = ('f32', fregs.get(i.reg_name(src.reg)))
                        sdef[d] = fdefs.get(i.reg_name(src.reg), []) + [i.address]
                    else:
                        stack[d] = regs.get(src.reg) or ('reg', i.reg_name(src.reg))
                        sdef[d] = rdef.get(src.reg, []) + [i.address]
            if mn.startswith('stm'):
                # stm rX,{a,b,...}   where rX is sp or 'add rX,sp,#imm'
                base = ops[0]
                sbase = None
                if base.type == ARM_OP_REG:
                    bv = regs.get(base.reg)
                    if i.reg_name(base.reg) == 'sp':
                        sbase = 0
                    elif bv and bv[0] == 'spoff':
                        sbase = bv[1]
                if sbase is not None:
                    for k, o in enumerate(ops[1:]):
                        d = sbase + k * 4
                        stack[d] = regs.get(o.reg) or ('reg', i.reg_name(o.reg))
                        sdef[d] = rdef.get(o.reg, []) + [i.address]
        # --- calls ---
        if mn in ('bl', 'blx') and ops and ops[-1].type == ARM_OP_IMM:
            tgt = ops[-1].imm
            callee = ctx.stubs.get(tgt & ~1) or ctx.stubs.get(tgt)
            sel = regs.get(_argreg(ctx, 1))
            selt = sel[1] if sel and sel[0] == 'sel' else None
            recv = regs.get(_argreg(ctx, 0))
            calls.append(dict(addr=i.address, target=tgt, callee=callee, sel=selt,
                              recv=recv, regs=dict(regs), fregs=dict(fregs),
                              stack=dict(stack), sdef=dict(sdef),
                              rdef=dict(rdef), fdef=dict(fdefs)))
            txt += f'   ; callee={callee} sel={selt!r}'
        if verbose:
            lines.append(txt)
    return calls, lines


def _argreg(ctx, n):
    from capstone.arm_const import ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3
    return (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3)[n]


def _iter_resync(ctx, start, end):
    """Decode [start,end) with full operand detail, resyncing past embedded
    literal pools. capstone stops at undecodable bytes; skipdata would give us
    'data' insns whose .operands raise. So step forward and restart instead."""
    sl = ctx.sl
    step = 2 if ctx.thumb else 4
    a = start
    while a < end:
        off = sl.addr_to_file(a)
        if off is None:
            return
        got = False
        for i in ctx.md.disasm(sl.data[off:off + (end - a)], a):
            got = True
            yield i
            a = i.address + i.size
        if not got:
            a += step

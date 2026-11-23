"""Annotating disassembler: resolves 1-step and 2-step pc-relative selector
loads, literal-pool float loads, and inline float immediates."""
import sys, os, struct
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zt import *  # noqa

MSGSEND = {6: {0x393fe0, 0x393fb0, 0x394004}, 9: {0x2d014c, 0x2d0118, 0x2d0170}}


def selrefs_map(sl):
    """addr -> selector string, for __objc_selrefs slots."""
    m = {}
    for s in sl.sections:
        if s.name != '__objc_selrefs':
            continue
        for i in range(s.size // 4):
            a = s.addr + i * 4
            p = struct.unpack_from('<I', sl.data, s.offset + i * 4)[0]
            t = ascii_str(sl, p)
            if t:
                m[a] = t
    return m


def deref_sel(sl, srmap, addr):
    """addr may be a selref slot, or a pointer to a selector string."""
    if addr in srmap:
        return srmap[addr]
    v = u32(sl, addr)
    if v is not None:
        t = ascii_str(sl, v)
        if t and 1 <= len(t) < 120:
            return t
    return None


def annotate(sl, start, end, thumb=None):
    """Yield (ins, note) with symbolic register tracking."""
    srmap = selrefs_map(sl)
    ins_list = dis(sl, start, end, thumb)
    th = (sl.subtype == 9) if thumb is None else thumb
    # reg -> ('imm', v) | ('sel', name) | ('selslot', addr) | ('addr', a)
    reg = {}
    fpr = {}
    out = []
    for ins in ins_list:
        pc = (ins.address + 4) & ~3 if th else ins.address + 8
        note = ''
        mn = ins.mnemonic
        ops = ins.op_str
        try:
            opl = ins.operands
        except Exception:
            opl = []

        def setr(rn, val):
            reg[rn] = val

        def rname(i):
            return ins.reg_name(opl[i].reg) if i < len(opl) else None

        # ---- pc-relative scalar loads
        if mn.startswith('ldr') and 'pc' in ops and '[pc, #' in ops:
            d = rname(0)
            try:
                off = opl[1].mem.disp
            except Exception:
                off = None
            if off is not None:
                a = pc + off
                v = u32(sl, a)
                setr(d, ('imm', v))
                nm = deref_sel(sl, srmap, v) if v else None
                note = f'-> [{a:#x}]={v:#x}'
                if nm:
                    note += f'  SEL?"{nm}"'
        elif mn.startswith('ldr') and '[pc, r' in ops:
            # ldr rD, [pc, rN]  -> rD = *(pc + rN)
            d = rname(0)
            try:
                b = ins.reg_name(opl[1].mem.index)
            except Exception:
                b = None
            base = reg.get(b)
            if base and base[0] == 'imm' and base[1] is not None:
                a = pc + base[1]
                v = u32(sl, a)
                nm = deref_sel(sl, srmap, a)
                setr(d, ('selslot', a, nm, v))
                note = f'-> slot {a:#x} = {v if v is None else hex(v)}'
                if nm:
                    note += f'  SEL "{nm}"'
            else:
                setr(d, None)
        elif mn.startswith('add') and ', pc' in ops.replace(' ', ' '):
            # add rD, pc, rN   (ARM)  /  add rD, pc  (Thumb)
            d = rname(0)
            src = None
            if len(opl) >= 3:
                try:
                    src = ins.reg_name(opl[2].reg)
                except Exception:
                    src = None
            elif len(opl) == 2:
                src = d
            base = reg.get(src)
            if base and base[0] == 'imm' and base[1] is not None:
                a = (pc + base[1]) & 0xFFFFFFFF
                nm = deref_sel(sl, srmap, a)
                setr(d, ('selslot', a, nm, u32(sl, a)))
                note = f'-> slot {a:#x}'
                if nm:
                    note += f'  SEL "{nm}"'
            else:
                setr(d, None)
        elif mn in ('mov', 'movw', 'mov.w') and len(opl) == 2 and opl[1].type == ARM_OP_IMM:
            setr(rname(0), ('imm', opl[1].imm))
        elif mn == 'movt' and len(opl) == 2 and opl[1].type == ARM_OP_IMM:
            d = rname(0)
            cur = reg.get(d)
            base = cur[1] if cur and cur[0] == 'imm' and cur[1] is not None else 0
            setr(d, ('imm', (base & 0xFFFF) | (opl[1].imm << 16)))
        elif mn == 'orr' and len(opl) == 3 and opl[2].type == ARM_OP_IMM:
            d = rname(0)
            s = ins.reg_name(opl[1].reg)
            cur = reg.get(s)
            if cur and cur[0] == 'imm' and cur[1] is not None:
                setr(d, ('imm', cur[1] | opl[2].imm))
                v = cur[1] | opl[2].imm
                note = f'= {v:#x}  f32={struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]}'
            else:
                setr(d, None)
        elif mn in ('mov', 'mov.w') and len(opl) == 2 and opl[1].type == ARM_OP_REG:
            setr(rname(0), reg.get(ins.reg_name(opl[1].reg)))
        # ---- VFP literal pool
        elif mn.startswith('vldr') and '[pc' in ops:
            d = rname(0)
            try:
                off = opl[1].mem.disp
            except Exception:
                off = None
            if off is not None:
                a = pc + off
                if d and (d.startswith('d') or d.startswith('q')):
                    b = rd(sl, a, 8)
                    val = f64(b) if b and len(b) == 8 else None
                    note = f'-> [{a:#x}] {b.hex() if b else "?"} f64={val}'
                else:
                    b = rd(sl, a, 4)
                    val = f32(b) if b and len(b) == 4 else None
                    note = f'-> [{a:#x}] {b.hex() if b else "?"} f32={val}'
                fpr[d] = val
        elif mn.startswith('vmov') and '#' in ops:
            d = rname(0)
            note = 'inline fp imm'
        # ---- calls
        if mn in ('bl', 'blx', 'bl.w', 'blx.w') and opl and opl[0].type == ARM_OP_IMM:
            tgt = opl[0].imm
            if tgt in MSGSEND.get(sl.subtype, ()):
                r1 = reg.get('r1')
                nm = None
                if r1:
                    if r1[0] == 'selslot':
                        nm = r1[2]
                    elif r1[0] == 'imm' and r1[1]:
                        nm = deref_sel(sl, srmap, r1[1])
                note = f'objc_msgSend  sel={nm!r}' + (('  ' + note) if note else '')
                reg = {k: v for k, v in reg.items() if k not in
                       ('r0', 'r1', 'r2', 'r3', 'r12', 'ip', 'lr')}
        out.append((ins, note))
    return out


def show(sl, start, end, thumb=None, only=None):
    for ins, note in annotate(sl, start, end, thumb):
        line = f'{ins.address:#08x}: {ins.bytes.hex():<8} {ins.mnemonic:<14} {ins.op_str}'
        if note:
            line += f'      ; {note}'
        if only and only not in line:
            continue
        print(line)

"""Reusable Thumb annotator for batch-2 items #2/#7/#8.

Annotates a method body with:
  * SEL names (selref table + direct cstring)
  * CFString literals  (`add rd, pc` / `ldr rd, [pc, #imm]` -> [isa,flags,data,len])
  * C strings
  * float constants materialised through movs/movt into a GPR, or `vldr sN,[pc,#x]`
  * `str rX, [sp, #n]` stack-argument slots (fontSize/dimensions live there)
  * objc_msgSend calls with the selector name + resolved args

Usage:
    from _t6_ann import Annotator, load
    a = Annotator(load())            # subtype 9 (thumb) by default
    a.dump_method("ZFZombieMenu", "initStatDisplay")
    a.scan("ZFZombieMenu", "initStatDisplay", {"setColor:", "setFontSize:"})
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import all_methods, classes_by_name  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import (  # noqa: E402
    ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC, ARM_REG_R0, ARM_REG_R1,
    ARM_REG_R2, ARM_REG_R3, ARM_REG_R12, ARM_REG_S0, ARM_REG_SP,
)

EXECUTABLE = "Payload/ZFR.app/ZFR"
DEFAULT_IPA = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v20fix.ipa"

MSGSEND = 0x2D014C
MSGSEND_STRET = 0x2D0170

# capstone ARM: r0..r12 == 66..78, sp == 12, lr == 10, pc == 11, s0 == 79
ARG_REGS = (ARM_REG_R2, ARM_REG_R3, ARM_REG_R12)
CLOBBER = (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12)


def load(ipa: str | Path | None = None, subtype: int = 9):
    if ipa:
        p = Path(ipa)
        if not p.is_absolute():
            cand = [Path.cwd() / p, ROOT / p, ROOT / "zombie_farm_ipa" / p]
            p = next((c for c in cand if c.exists()), cand[0])
    else:
        p = ROOT / "zombie_farm_ipa" / DEFAULT_IPA
    with zipfile.ZipFile(p) as z:
        fat = z.read(EXECUTABLE)
    return next(s for s in parse_fat(fat) if s.subtype == subtype)


class Annotator:
    def __init__(self, sl):
        self.sl = sl
        self.sel_at: dict[int, str] = {}      # selref slot addr -> selector
        self.sel_cstr: dict[int, str] = {}    # cstring addr -> selector
        for sec in sl.sections:
            if sec.name != "__objc_selrefs":
                continue
            for off in range(0, sec.size, 4):
                a = sec.addr + off
                v = self._u32(a)
                if v:
                    t = self.cstr(v)
                    if t and not t.startswith("<"):
                        self.sel_at[a] = t
                        self.sel_cstr[v] = t
        self.by_name = classes_by_name(sl)
        self.secs = {s.name: s for s in sl.sections}
        self.md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        self.md.detail = True
        self.md.skipdata = True
        self._cf_cache: dict[int, object] = {}
        self._ptr_cache: dict[int, str] = {}
        self._methods_cache: dict[str, list] = {}
        self._ordered_cache: dict[str, list] = {}

    # ---------------- primitives ----------------
    def _u32(self, a):
        o = self.sl.addr_to_file(a)
        if o is None or o + 4 > len(self.sl.data):
            return None
        return struct.unpack_from("<I", self.sl.data, o)[0]

    def _bytes(self, a, n):
        o = self.sl.addr_to_file(a)
        if o is None or o + n > len(self.sl.data):
            return None
        return self.sl.data[o:o + n]

    def cstr(self, a, limit=200):
        o = self.sl.addr_to_file(a)
        if o is None:
            return None
        try:
            e = self.sl.data.index(b"\0", o, o + limit)
        except ValueError:
            return None
        try:
            s = self.sl.data[o:e].decode("utf-8")
        except Exception:
            return None
        return s if s and s.isprintable() else None

    def cfstring(self, a):
        """If `a` is a CFString object, return (text, raw16)."""
        hit = self._cf_cache.get(a, 0)
        if hit != 0:
            return hit
        res = None
        for name in ("__cfstring", "__const"):
            sec = self.secs.get(name)
            if sec and sec.addr <= a < sec.addr + sec.size:
                raw = self._bytes(a, 16)
                if not raw:
                    break
                isa, flags, data, ln = struct.unpack("<IIII", raw)
                if not (0x7C0 <= flags <= 0x7FF) or ln > 4096:
                    break
                res = (self._decode_cf(data, ln), raw)
                break
        self._cf_cache[a] = res
        return res

    def _decode_cf(self, data, ln):
        b = self._bytes(data, ln)
        if b is None:
            return "<bad %#x>" % data
        for enc in ("utf-8", "utf-16-be"):
            try:
                s = b.decode(enc)
            except Exception:
                continue
            if s.isprintable() or not s.strip("\n\t \r"):
                return s
        return repr(b)

    def ptr(self, a):
        """Human description of an address that may be a CFString/cstring/sel."""
        if not isinstance(a, int):
            return ""
        hit = self._ptr_cache.get(a)
        if hit is not None:
            return hit
        out = ""
        cf = self.cfstring(a)
        if cf is not None:
            out = "CFSTR %r" % (cf[0],)
        else:
            s = self.cstr(a)
            if s:
                out = ("SEL " if a in self.sel_cstr else "CSTR ") + repr(s)
        self._ptr_cache[a] = out
        return out

    @staticmethod
    def f32(v):
        if isinstance(v, float):
            return "f32 %g" % v
        if isinstance(v, int) and 0x38000000 <= (v & 0xFFFFFFFF) <= 0x45000000:
            return "f32 %g" % struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]
        return ""

    def desc(self, v):
        if isinstance(v, float):
            return "f32 %g" % v
        if isinstance(v, int):
            return self.ptr(v) or self.f32(v) or ("%#x" % v)
        return "?"

    # ---------------- method discovery ----------------
    _starts = None

    def starts(self):
        if self._starts is None:
            s = set()
            for c, i in self.by_name.values():
                for m in self.methods_of(c, i):
                    if m.imp:
                        s.add(m.imp & ~1)
            self._starts = sorted(s)
        return self._starts

    def methods_of(self, cls, info):
        """Cached instance+class method list for one class."""
        key = info["name"]
        got = self._methods_cache.get(key)
        if got is None:
            got = all_methods(self.sl, cls, info)
            self._methods_cache[key] = got
        return got

    def ordered_methods(self, cls_name):
        """[(start, selector, Method)] sorted by address for one class."""
        got = self._ordered_cache.get(cls_name)
        if got is None:
            cls, info = self.by_name[cls_name]
            got = sorted(((m.imp & ~1), m.selector, m) for m in self.methods_of(cls, info) if m.imp)
            self._ordered_cache[cls_name] = got
        return got

    def method_range(self, cls_name, selector):
        st = self.starts()
        for start, sel, m in self.ordered_methods(cls_name):
            if sel != selector:
                continue
            end = next((s for s in st if s > start), start + 0x400)
            return m, start, end
        return None, None, None

    # ---------------- core ----------------
    def disasm(self, start, end):
        """Disassemble the half-open address range [start, end)."""
        if end <= start:
            return []
        o = self.sl.addr_to_file(start)
        if o is None:
            return []
        return list(self.md.disasm(self.sl.data[o:o + (end - start)], start))

    def annotate(self, ins):
        regs: dict[int, object] = {}
        stack: dict[int, object] = {}
        sregs: dict[int, object] = {}
        out = []
        for x in ins:
            if not x.id or not x.operands:
                regs, stack, sregs = {}, {}, {}
                out.append((x, "<data>", {}))
                continue
            ops = x.operands
            m = x.mnemonic.split(".")[0]
            ann = ""
            dst = None
            nv = None

            if m in ("movw", "movt") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
                dst = ops[0].reg
                imm = ops[-1].imm & 0xFFFF
                if m == "movw":
                    nv = imm
                else:
                    lo = regs.get(dst)
                    nv = (imm << 16) | (lo & 0xFFFF if isinstance(lo, int) else 0)
                ann = self.f32(nv)
            elif m == "mov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
                dst = ops[0].reg
                nv = regs.get(ops[1].reg, sregs.get(ops[1].reg))
                if ops[1].reg >= ARM_REG_S0 and isinstance(sregs.get(ops[1].reg), float):
                    nv = sregs[ops[1].reg]
                ann = self.desc(nv)
            elif m in ("mov", "movs") and ops[0].type == ARM_OP_REG and ops[-1].type == ARM_OP_IMM:
                dst = ops[0].reg
                nv = ops[-1].imm
                ann = self.f32(nv)
            elif m == "vmov" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG:
                if ops[0].reg >= ARM_REG_S0 and ops[1].reg < ARM_REG_S0:
                    sregs[ops[0].reg] = regs.get(ops[1].reg)
                elif ops[1].reg >= ARM_REG_S0 and ops[0].reg < ARM_REG_S0:
                    dst = ops[0].reg
                    nv = sregs.get(ops[1].reg)
                    ann = self.desc(nv)
            elif m == "add" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
                    and ops[1].reg == ARM_REG_PC:
                v = regs.get(ops[0].reg)
                if isinstance(v, int):
                    dst = ops[0].reg
                    nv = ((x.address + 4) + v) & 0xFFFFFFFF
                    ann = self.ptr(nv)
            elif m == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG \
                    and ops[2].type == ARM_OP_IMM:
                base = regs.get(ops[1].reg)
                dst = ops[0].reg
                nv = ((base + ops[2].imm) & 0xFFFFFFFF) if isinstance(base, int) else None
                ann = self.ptr(nv) if nv else ""
            elif m == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
                mm = ops[1].mem
                dst = ops[0].reg
                if mm.base == ARM_REG_PC:
                    pcw = (x.address + 4) & ~3
                    idx = regs.get(mm.index) if mm.index else 0
                    if isinstance(idx, int):
                        eff = (pcw + (mm.disp or 0) + idx) & 0xFFFFFFFF
                        v = self._u32(eff)
                        nv = v
                        if eff in self.sel_at:
                            ann = "SEL " + self.sel_at[eff]
                        elif isinstance(v, int) and v in self.sel_cstr:
                            ann = "SEL " + self.sel_cstr[v]
                        elif isinstance(v, int):
                            ann = self.ptr(v) or ("@%#x=%#x" % (eff, v))
                elif mm.base == ARM_REG_SP and not mm.index:
                    v = stack.get(mm.disp or 0)
                    nv = v
                    ann = "SP+%#x" % (mm.disp or 0)
                    d = self.desc(v)
                    if d != "?":
                        ann += " = " + d
                else:
                    base = regs.get(mm.base)
                    if isinstance(base, int) and not mm.index:
                        eff = (base + (mm.disp or 0)) & 0xFFFFFFFF
                        v = self._u32(eff)
                        nv = v
                        if eff in self.sel_at:
                            ann = "SEL " + self.sel_at[eff]
                        elif isinstance(v, int):
                            ann = self.ptr(v) or ("@%#x=%#x" % (eff, v))
                    else:
                        nv = None
            elif m == "vldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
                mm = ops[1].mem
                if mm.base == ARM_REG_PC and ops[0].reg >= ARM_REG_S0:
                    pcw = (x.address + 4) & ~3
                    eff = (pcw + (mm.disp or 0)) & 0xFFFFFFFF
                    b = self._bytes(eff, 4)
                    if b:
                        val = struct.unpack("<f", b)[0]
                        sregs[ops[0].reg] = val
                        ann = "f32 %g  [pool %#x = %s]" % (val, eff, b.hex())
            elif m == "str" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
                mm = ops[1].mem
                if mm.base == ARM_REG_SP and not mm.index:
                    src = sregs.get(ops[0].reg, regs.get(ops[0].reg))
                    stack[mm.disp or 0] = src
                    ann = "-> SP+%#x" % (mm.disp or 0)
                    d = self.desc(src)
                    if d != "?":
                        ann += " = " + d
            elif m in ("stm", "stmia") and ops[0].type == ARM_OP_REG and ops[0].reg == ARM_REG_SP:
                base_off = 0
                for op in ops[1:]:
                    if op.type == ARM_OP_REG:
                        stack[base_off] = sregs.get(op.reg, regs.get(op.reg))
                        base_off += 4
                ann = "-> SP store-multiple"
            elif m in ("bl", "blx") and ops and ops[0].type == ARM_OP_IMM:
                t = ops[0].imm & ~1
                if t in (MSGSEND, MSGSEND_STRET):
                    r1v = regs.get(ARM_REG_R1)
                    nm = None
                    if isinstance(r1v, int):
                        nm = self.sel_at.get(r1v) or self.sel_cstr.get(r1v)
                    args = [self.desc(regs.get(r)) for r in ARG_REGS]
                    for k in sorted(stack):
                        d = self.desc(stack[k])
                        if d != "?":
                            args.append("sp+%#x=%s" % (k, d))
                    ann = "MSG %s(%s)" % (nm or "?", ", ".join(args))
                else:
                    sym = self.sl.symbols.get(t)
                    ann = "call %#x%s" % (t, (" <%s>" % sym) if sym else "")
                for r in CLOBBER:
                    regs.pop(r, None)
                out.append((x, ann, dict(regs)))
                continue

            if dst is not None:
                regs[dst] = nv
            out.append((x, ann, dict(regs)))
        return out

    # ---------------- reporting ----------------
    def dump_range(self, start, end):
        print("---- range %#x..%#x" % (start, end))
        for x, ann, _ in self.annotate(self.disasm(start, end)):
            print("  %#010x  %-8s %-42s %s" % (x.address, x.mnemonic, x.op_str, ann))

    def dump_method(self, cls_name, selector, limit=0x800):
        m, start, end = self.method_range(cls_name, selector)
        if m is None:
            print("!! %s %s not found" % (cls_name, selector))
            return
        print("=" * 108)
        print("-- [%s] %s -%s   imp=%#x range=%#x..%#x"
              % (m.kind, cls_name, selector, m.imp, start, end))
        print("=" * 108)
        for x, ann, _ in self.annotate(self.disasm(start, min(end, start + limit))):
            print("  %#010x  %-8s %-42s %s" % (x.address, x.mnemonic, x.op_str, ann))

    def scan(self, cls_name, selector, want, ctx=0):
        """Print only the objc_msgSend calls whose selector is in `want`."""
        m, start, end = self.method_range(cls_name, selector)
        if m is None:
            print("!! %s %s not found" % (cls_name, selector))
            return
        print("### %s -%s  (%#x..%#x)" % (cls_name, selector, start, end))
        rows = self.annotate(self.disasm(start, end))
        for i, (x, ann, _) in enumerate(rows):
            if not ann.startswith("MSG "):
                continue
            name = ann[4:].split("(", 1)[0]
            if name in want:
                print("   %#010x  %s" % (x.address, ann))
                for j in range(max(0, i - ctx), i):
                    px, pann, _ = rows[j]
                    print("        .. %#010x  %-8s %-38s %s" % (px.address, px.mnemonic, px.op_str, pann))

    def scan_class(self, cls_name, want, selectors=None):
        if cls_name not in self.by_name:
            print("!! class %s not found" % cls_name)
            return
        for _, sel, _m in self.ordered_methods(cls_name):
            if selectors and sel not in selectors:
                continue
            self.scan(cls_name, sel, want)


def main():
    argv = sys.argv[1:]
    ipa = None
    if argv and argv[0].endswith(".ipa"):
        ipa = argv.pop(0)
    a = Annotator(load(ipa))
    if len(argv) >= 2:
        a.dump_method(argv[0], argv[1])


if __name__ == "__main__":
    main()

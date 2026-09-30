"""Reachability analysis of the Thumb slice so a stub can be placed in code that
is provably never executed.

Starters: every ObjC method IMP (classes, metaclasses and categories) plus the
__mod_init_func entries.  Follows fallthrough, all direct conditional and
unconditional branches and bl/blx; treats `bx <reg>`, `pop {..,pc}`, indirect
`ldr pc, ...` and `tbb/tbh` as terminators (their targets, if any, are unknown).

Anything no walk reaches is reported as a candidate cave.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 64

a = Annotator(load())
sl = a.sl
txt = next(s for s in sl.sections if s.name == "__text")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

start_addr = txt.addr
end_addr = txt.addr + txt.size
off = txt.offset
code = sl.data[off:off + txt.size]

ins = {}
for x in md.disasm(code, start_addr):
    ins[x.address] = x
print("instructions decoded: %d" % len(ins), file=sys.stderr)

starters = set()
for m in sl.methods:
    if m.imp:
        starters.add(m.imp & ~1)
for sec in sl.sections:
    if sec.name == "__mod_init_func":
        for k in range(0, sec.size, 4):
            v = struct.unpack_from("<I", sl.data, sec.offset + k)[0]
            if v:
                starters.add(v & ~1)
print("starters: %d" % len(starters), file=sys.stderr)

visited = set()
work = [s for s in starters if s in ins]
targets = set()
while work:
    addr = work.pop()
    while True:
        if addr in visited or addr not in ins:
            break
        visited.add(addr)
        x = ins[addr]
        m = x.mnemonic.split(".")[0]
        nxt = x.address + x.size
        terminator = False
        if m in ("b", "bl", "blx", "cbz", "cbnz"):
            if x.operands and x.operands[-1].type == 2:      # immediate
                tgt = x.operands[-1].imm & ~1
                targets.add(tgt)
                if m == "b":
                    addr = tgt
                    continue
                if tgt in ins:
                    work.append(tgt)
            if m in ("cbz", "cbnz"):
                addr = nxt
                continue
        elif m.startswith("b") and m not in ("bic", "bfi", "bfc"):
            # conditional branch (beq, bne, blo ...)
            if x.operands and x.operands[-1].type == 2:
                tgt = x.operands[-1].imm & ~1
                targets.add(tgt)
                if tgt in ins:
                    work.append(tgt)
        elif m in ("pop",) and "pc" in x.op_str:
            terminator = True
        elif m == "bx" or m == "blx":
            if x.operands and x.operands[0].type == 1:       # register
                terminator = True
        elif m == "ldr" and x.op_str.startswith("pc,"):
            terminator = True
        elif m in ("tbb", "tbh"):
            terminator = True
        if terminator:
            break
        addr = nxt

# literal-pool reads also count as "used"
used_data = set()
for addr in visited:
    x = ins[addr]
    m = x.mnemonic.split(".")[0]
    if m == "ldr" and "[pc" in x.op_str:
        base = (addr + 4) & ~3
        try:
            disp = int(x.op_str.split("#")[1].rstrip("]"), 0)
        except Exception:
            disp = 0
        for k in range(4):
            used_data.add(base + disp + k)
    if m == "add" and x.op_str.endswith(", pc"):
        try:
            reg = x.op_str.split(",")[0].strip()
            imm = a._u32  # noqa
        except Exception:
            pass

print("visited: %d  branch targets: %d" % (len(visited), len(targets)), file=sys.stderr)

# find gaps
runs = []
cur = None
for addr in range(start_addr, end_addr, 2):
    live = addr in visited or addr in targets
    if not live:
        if cur is None:
            cur = addr
    else:
        if cur is not None and addr - cur >= MIN:
            runs.append((cur, addr - cur))
        cur = None
if cur is not None and end_addr - cur >= MIN:
    runs.append((cur, end_addr - cur))

print("=== candidate caves (>= %d bytes, sub%d) ===" % (MIN, sl.subtype))
for addr, ln in runs:
    data = sl.data[sl.addr_to_file(addr):sl.addr_to_file(addr) + min(ln, 16)]
    print("   %#08x len=%4d  %s" % (addr, ln, data.hex(" ")))

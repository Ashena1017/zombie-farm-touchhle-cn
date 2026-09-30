"""Is an address range referenced by any branch or pc-relative data access?

    python _v21_refs.py START END
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import load
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

lo = int(sys.argv[1], 0)
hi = int(sys.argv[2], 0)
sl = load()
txt = next(s for s in sl.sections if s.name == "__text")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True

hits = []
for x in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
    try:
        if not x.operands or not x.id:
            continue
    except Exception:
        continue
    m = x.mnemonic.split(".")[0]
    if m in ("b", "bl", "blx", "cbz", "cbnz") or (m.startswith("b") and m not in ("bic", "bfi", "bfc")):
        op = x.operands[-1]
        if op.type == ARM_OP_IMM and lo <= (op.imm & ~1) < hi:
            hits.append((x.address, "branch", op.imm & ~1))
    if m in ("ldr", "vldr") and x.operands[1].type == ARM_OP_MEM and x.operands[1].mem.base == ARM_REG_PC:
        base = (x.address + 4) & ~3
        eff = base + (x.operands[1].mem.disp or 0)
        if lo <= eff < hi:
            hits.append((x.address, "litpool@%#x" % eff, eff))
    print("references into [%#x,%#x):" % (lo, hi))
for a, kind, t in hits:
    print("   %#010x  %s -> %#x" % (a, kind, t))
print("total %d" % len(hits))

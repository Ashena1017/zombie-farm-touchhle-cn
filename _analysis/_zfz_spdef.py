#!/usr/bin/env python3
"""Path-aware: which [sp,#slot] stores can actually REACH the target instruction?

A store S can reach target T iff S is reachable from ENTRY and T is reachable from S.
Prints the immediate value stored (constant only), so we can tell what the 4th
argument (`table:`) of -[NSBundle localizedStringForKey:value:table:] is at the
`Fertilized by %@!` site.

Usage: python _analysis/_zfz_spdef.py CLASS SELECTOR ENTRY TARGET SLOT
"""
from __future__ import annotations

import pathlib as _pl
import sys
from collections import deque

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
from _t6_ann import Annotator, load  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_SP  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos[4:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
CLS, SEL = pos[0], pos[1]
ENTRY, TARGET, SLOT = int(pos[2], 0), int(pos[3], 0), int(pos[4], 0)

a = Annotator(load(IPA, subtype=9))
m, start, end = a.method_range(CLS, SEL)
rows = a.annotate(a.disasm(start, end))
ins = [x for x, _, _ in rows]
ann = {x.address: s for x, s, _ in rows}
regs_at = {x.address: r for x, _, r in rows}
by = {x.address: i for i, x in enumerate(ins)}
print("### %s -%s  %#x..%#x ; entry %#x -> target %#x ; slot sp+%#x"
      % (CLS, SEL, start, end, ENTRY, TARGET, SLOT))


def is_branch(x):
    return x.mnemonic.startswith("b") and x.mnemonic not in ("bic", "bfi", "bfc")


def terminates(x):
    return (x.mnemonic in ("b", "b.w") or x.mnemonic.startswith("bx")
            or (x.mnemonic.startswith("pop") and "pc" in x.op_str))


def succs(addr):
    i = by.get(addr)
    if i is None:
        return []
    x = ins[i]
    out = []
    if is_branch(x) and x.operands and x.operands[0].type == ARM_OP_IMM:
        t = x.operands[0].imm
        if start <= t < end:
            out.append(t)
    if not terminates(x) and i + 1 < len(ins):
        out.append(ins[i + 1].address)
    return out


def reach(src):
    seen, q = {src}, deque([src])
    while q:
        u = q.popleft()
        for v in succs(u):
            if v not in seen:
                seen.add(v)
                q.append(v)
    return seen


from_entry = reach(ENTRY)
from_target = reach(TARGET)          # forward from target; we need BACKWARD
# backward reachability to target: build reverse graph over the whole method
pred = {}
for x in ins:
    for v in succs(x.address):
        pred.setdefault(v, set()).add(x.address)
can_reach_target, q = {TARGET}, deque([TARGET])
while q:
    u = q.popleft()
    for p in pred.get(u, ()):
        if p not in can_reach_target:
            can_reach_target.add(p)
            q.append(p)

print("    %d insns reachable from entry; %d can reach target" % (len(from_entry), len(can_reach_target)))

print("\n### [sp,#%#x] stores that are BOTH reachable from entry AND can reach target" % SLOT)
n = 0
for x in ins:
    if x.address not in from_entry or x.address not in can_reach_target:
        continue
    ops = x.operands
    if not ops or len(ops) != 2 or not x.mnemonic.startswith("str"):
        continue
    if ops[1].type != ARM_OP_MEM:
        continue
    mm = ops[1].mem
    if mm.base != ARM_REG_SP or mm.index or (mm.disp or 0) != SLOT:
        continue
    n += 1
    src = ops[0]
    v = regs_at[x.address].get(src.reg) if src.type == 1 else None
    print("   %#010x  %-8s %-30s  src r%-2d = %s   %s"
          % (x.address, x.mnemonic, x.op_str, src.reg, ("%#x" % v) if isinstance(v, int) else "?",
             ann[x.address]))
print("   total %d" % n)

# also: does EVERY path entry->target pass through one of these?
print("\n### is the target reachable if we DELETE those stores?")
blocked = set()
for x in ins:
    if x.address not in from_entry or x.address not in can_reach_target:
        continue
    ops = x.operands
    if not ops or len(ops) != 2 or not x.mnemonic.startswith("str") or ops[1].type != ARM_OP_MEM:
        continue
    mm = ops[1].mem
    if mm.base == ARM_REG_SP and not mm.index and (mm.disp or 0) == SLOT:
        blocked.add(x.address)


def succs_nb(addr):
    i = by.get(addr)
    if i is None:
        return []
    x = ins[i]
    out = []
    if is_branch(x) and x.operands and x.operands[0].type == ARM_OP_IMM:
        t = x.operands[0].imm
        if start <= t < end:
            out.append(t)
    if not terminates(x) and i + 1 < len(ins) and ins[i + 1].address not in blocked:
        out.append(ins[i + 1].address)
    return [o for o in out if o not in blocked]


seen, q = {ENTRY}, deque([ENTRY])
while q:
    u = q.popleft()
    for v in succs_nb(u):
        if v not in seen:
            seen.add(v)
            q.append(v)
print("   blocked stores: %s" % sorted("%#x" % b for b in blocked))
print("   target still reachable? %s" % (TARGET in seen))

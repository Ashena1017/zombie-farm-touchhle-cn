#!/usr/bin/env python3
"""Verify every factual claim the README's new 5.11 / 6.3-6.5 sections make.

If any assertion here fails, the README text is wrong and must be fixed.
Read-only.

NOTE on earlier failures: the first version of this script reported 5 failures
that were all bugs in the SCRIPT, not the README:
  * NOP padding is bytes `00 bf` (halfword 0xbf00 little-endian), not `bf 00`;
  * selector names do not appear in raw capstone text - they must be resolved
    through the __objc_selrefs pool, so "does it call removeObserver:" cannot be
    answered by substring search on the disassembly;
  * a classref annotation is not part of the instruction text either.
Fixed below, so the checks now test the README rather than the script.
"""
from __future__ import annotations

import re
import struct
import sys
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from audit_zfr_ipa import parse_fat  # noqa: E402
from patch_zfr_alert_fonts import EXECUTABLE  # noqa: E402
from inspect_v3_facts import ascii_str, u32  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
Z = ROOT / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
V27 = Z / f"{BASE}.fixed-fonts-v27fix.ipa"
V28 = Z / f"{BASE}.fixed-fonts-v28fix.ipa"
V6 = Z / f"{BASE}.fixed-fonts-v6.ipa"          # last IPA before the v10/v11 rewrite

NOP_THUMB = b"\x00\xbf"                        # 0xbf00 little-endian
FAIL = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def exe(p):
    with zipfile.ZipFile(p) as z:
        return z.read(EXECUTABLE)


def selectors_in(sl, raw, addr, mode):
    """Selector names for every objc_msgSend call in this code.

    Reuses the project's own annotator (`annot_disasm.annotate`), which already
    handles the `movw/movt` + `add rX, pc` + `ldr rX, [rX]` PIC idiom. Hand-rolling
    this was the source of two false failures in the first version of this script.
    """
    from annot_disasm import annotate, method_index

    thumb = mode == CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, mode)
    md.detail = True
    idx = method_index(sl)
    regs: dict = {}
    out = []
    for i in md.disasm(raw, addr):
        if not i.id:
            regs.clear()
            continue
        note = annotate(sl, i, thumb, idx, regs)
        if i.mnemonic in ("bl", "blx") and i.operands and i.operands[0].type == 2 \
                and i.operands[0].imm == 0x2D014C:
            m = re.search(r"sel='([^']*)'", note)
            out.append(m.group(1) if m else None)
    return out


v28, v27, v6 = exe(V28), exe(V27), exe(V6)
s28 = {s.subtype: s for s in parse_fat(v28)}
s27 = {s.subtype: s for s in parse_fat(v27)}
s6 = {s.subtype: s for s in parse_fat(v6)}
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

print("== 5.11: v11 left the body as NOP padding, so v28 fits in place ==")
raw27 = s27[9].data[s27[9].addr_to_file(0x10A1DC):s27[9].addr_to_file(0x10A29C)]
tail = 0
for i in range(len(raw27) - 2, -1, -2):
    if raw27[i:i + 2] == NOP_THUMB:
        tail += 2
    else:
        break
check(tail >= 0x80,
      "v27 (v11's output) had %#x bytes of trailing NOP padding" % tail)
real27 = len(raw27) - tail
check(real27 <= 0x40,
      "v11's actual code was only %#x bytes (removeObserver:self alone)" % real27)

print("\n== 5.11: v28's restored loop ==")
b28 = s28[9].data[s28[9].addr_to_file(0x10A1DC):s28[9].addr_to_file(0x10A29C)]
check(len(b28) == 0xC0, "v28 sub9 region is exactly %#x bytes" % len(b28))
sels = selectors_in(s28[9], b28, 0x10A1DC, CS_MODE_THUMB)
check(len(sels) == 6, "6 objc_msgSend calls (%d)" % len(sels))
check(sels.count("removeObserver:") == 2,
      "removeObserver: called twice - self then each requirement (%r)" % sels)
check(sels[0] == "defaultCenter", "first call is defaultCenter")
check(sels[1] == "removeObserver:", "second call is removeObserver:self (v11's fix)")
check(sels[2] == "requirements", "third call reads self.requirements")
check(sels[3] == "count", "fourth reads count")
check(sels[4] == "objectAtIndex:", "fifth reads objectAtIndex:")
check(sels[5] == "removeObserver:", "sixth is the per-requirement removeObserver:")
real = [x for x in md.disasm(b28, 0x10A1DC) if x.mnemonic != "nop"]
code_len = sum(x.size for x in real)
check(code_len == 0x8A, "v28 real code is %#x bytes (README says 0x8a)" % code_len)

print("\n== 5.11: the base (pre-v11) stopListening removed per-requirement ==")
raw6 = s6[9].data[s6[9].addr_to_file(0x10A1DC):s6[9].addr_to_file(0x10A29C)]
check(len(raw6) == 0xC0, "base body is %#x bytes (README says 0xc0)" % len(raw6))
base_sels = selectors_in(s6[9], raw6, 0x10A1DC, CS_MODE_THUMB)
check("removeObserver:" in base_sels, "base calls removeObserver: (%r)" % base_sels)
check("countByEnumeratingWithState:objects:count:" in base_sels,
      "base used fast enumeration, as the README says (%r)" % base_sels)
real6 = [x for x in md.disasm(raw6, 0x10A1DC)
         if not (x.mnemonic == "nop" or (x.mnemonic == "mov" and x.op_str == "r0, r0"))]
orig_len = sum(x.size for x in real6)
check(orig_len == 0xBE, "base real code is %#x bytes" % orig_len)
check(orig_len + 0x0E > 0xC0,
      "base %#x + ~0xe for removeObserver:self = %#x > 0xc0 (so fast enum would not fit)"
      % (orig_len, orig_len + 0x0E))

print("\n== 5.11: each notification builds its OWN requirement objects ==")
# The classref slot used at 0x109b2a (movw/movt at 0x109b22/0x109b26)
site = s28[9].data[s28[9].addr_to_file(0x109B22):s28[9].addr_to_file(0x109B2C)]
got_target = None
pending = {}
for x in md.disasm(site, 0x109B22):
    ops = x.operands
    if x.mnemonic == "movw" and len(ops) == 2:
        pending[ops[0].reg] = ops[1].imm & 0xFFFF
    elif x.mnemonic == "movt" and len(ops) == 2:
        pending[ops[0].reg] = pending.get(ops[0].reg, 0) | ((ops[1].imm & 0xFFFF) << 16)
    elif x.mnemonic == "add" and len(ops) == 2 and ops[1].type == 1:
        got_target = (x.address + 4 + pending[ops[0].reg]) & 0xFFFFFFFF
check(got_target == 0x39A2E8,
      "0x109b2a resolves classref slot %s (expect 0x39a2e8)"
      % (hex(got_target) if got_target else None))
cls = u32(s28[9], 0x39A2E8)
ro = u32(s28[9], cls + 16)
name = s28[9].cstr(u32(s28[9], ro + 16))
check(name == "ZFQuestRequirement", "classref 0x39a2e8 -> %r" % name)
check(u32(s28[9], 0x3BB9C4) == 0x128,
      "ivar slot 0x3bb9c4 = %#x (requirements)" % u32(s28[9], 0x3BB9C4))
# a fresh NSMutableArray is allocated in initWithID:loadSprite:
# NOTE: feed the WHOLE method (entry 0x1096ec), not a window. The annotator
# tracks movw/movt per register, so a slice that starts mid-method has no valid
# state and reports the type-encoding string ('v12@0:4@8') instead of 'alloc'.
# Two earlier "failures" in this script came from exactly that mistake.
sels2 = selectors_in(s28[9], s28[9].data[s28[9].addr_to_file(0x1096EC):
                                s28[9].addr_to_file(0x109D3C)],
                    0x1096EC, CS_MODE_THUMB)
check("alloc" in sels2 and "init" in sels2,
      "initWithID:loadSprite: allocates a fresh array")
check(sels2.count("alloc") >= 1 and "arrayWithContentsOfFile:" in sels2,
      "and reads Quests.plist via arrayWithContentsOfFile:")

print("\n== 5.11: sub6 pool is 6 words at 0x16a700..0x16a718 ==")
s6v28 = s28[6]
pool = s6v28.data[s6v28.addr_to_file(0x16A700):s6v28.addr_to_file(0x16A718)]
check(len(pool) == 24, "sub6 pool region is %d bytes" % len(pool))
words = struct.unpack("<6I", pool)
want = [0x45DF24, 0x457D44, 0x457DC4, 0x45A310, 0x457B20, 0x457B58]
check(list(words) == want, "pool words are the 6 expected slots")
# slot 0 is a __objc_classrefs entry (dyld-bound -> 0 at rest);
# the rest are __objc_selrefs entries, which point straight at selector strings.
check(u32(s6v28, 0x45DF24) == 0,
      "0x45df24 is a classref slot, 0 at rest (dyld-bound)")
for slot, name in ((0x457D44, "defaultCenter"), (0x457DC4, "removeObserver:"),
                   (0x45A310, "requirements"), (0x457B20, "count"),
                   (0x457B58, "objectAtIndex:")):
    got = ascii_str(s6v28, u32(s6v28, slot))
    check(got == name, "selref %#x -> %r" % (slot, got))

print("\n== environment claims ==")
try:
    import keystone
    check(True, "keystone importable (%s)" % getattr(keystone, "__version__", "?"))
except Exception as ex:
    check(False, "keystone not importable: %s" % ex)
# capstone push/pop operand model (the README documents one-operand-per-register)
ins = list(md.disasm(bytes.fromhex("f0b5"), 0x1000))[0]
check(not hasattr(ins.operands[0], "regs"),
      "capstone push has no .regs (README says collect .reg across operands)")
check(len(ins.operands) == 5, "push {r4,r5,r6,r7,lr} = 5 operands (one per reg)")

print("\n== the v28 report exists and states the correction ==")
rep = ROOT / "_analysis" / "reports" / "ZFR_v28fix_任务闪退根因修复.md"
check(rep.exists(), "report file present")
if rep.exists():
    txt = rep.read_text(encoding="utf-8")
    check("dismissAlertPositive" in txt, "report records the bigCheck/bigX correction")
    check("同类复用" in txt, "report explains the same-class address-reuse blind spot")
    check("订正" in txt, "report marks the correction explicitly")

print()
if FAIL:
    print("README CLAIMS FAILED (%d):" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL README CLAIMS VERIFIED")

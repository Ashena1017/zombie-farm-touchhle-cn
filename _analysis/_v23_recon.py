"""v23 recon: (a) which register feeds title1's dimensions.height, (b) the
explicit setColor: on the ABILITY tab label."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

IPA = "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v22fix.ipa"
a = Annotator(load(IPA))
sl = a.sl
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

print("== track r5 / fp in ZFAlertWindow -alertWindowSlideInInformative:... ==")
m, start, end = a.method_range(
    "ZFAlertWindow",
    "alertWindowSlideInInformative:withMessage:withSprite:withHudFile:"
    "withButtonRect:withButtonSelectedRect:withButtonText:withButtonColor:"
    "slideFromLeft:")
rows = a.annotate(a.disasm(start, end))
for x, ann, regs in rows:
    if x.address > 0x76BA2:
        break
    if not (0x76A90 <= x.address <= 0x76BA0):
        continue
    mark = ""
    if x.operands and x.operands[0].type == 1 and x.operands[0].reg in (5, 11):
        mark = "   <<< writes r%d" % (x.operands[0].reg if x.operands[0].reg == 5 else 11)
    print("  %#010x  %-8s %-40s %-28s%s" % (x.address, x.mnemonic, x.op_str, ann, mark))
v5 = None
for x, ann, regs in rows:
    if x.address >= 0x76B8A:
        break
    if x.operands and x.operands[0].type == 1 and x.operands[0].reg == 5:
        v5 = (x.address, ann)
print("  last write to r5 before 0x76b8a: %s" % (("%#x  %s" % v5) if v5 else "none"))

print("\n== bytes around 0xcfb1e (ABILITY setColor) ==")
o = sl.addr_to_file(0xCFB1A)
for k in range(0, 16, 2):
    addr = 0xCFB1A + k
    b = sl.data[o + k:o + k + 4]
    ins = list(md.disasm(b, addr))
    t = ("%s %s" % (ins[0].mnemonic, ins[0].op_str)) if ins and ins[0].size <= 4 else "?"
    print("  %#010x  %-10s %s" % (addr, b[:2].hex(), t))

print("\n== bytes at 0x76b8a (stm.w sp, {r5, fp}) and 0x76aaa (movt r5) ==")
for addr in (0x76B8A, 0x76AAA, 0x76B9C):
    o = sl.addr_to_file(addr)
    b = sl.data[o:o + 4]
    ins = list(md.disasm(b, addr))
    print("  %#010x  %-10s %s" % (addr, b.hex(), ("%s %s" % (ins[0].mnemonic, ins[0].op_str)) if ins else "?"))

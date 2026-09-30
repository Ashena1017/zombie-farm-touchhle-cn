"""#7 recon: confirm the five CJK-path label factories in the current build and
the free dead-code pocket for the setColor: stub."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

SITES = [
    (0x0CF962, "ZFZombieMenu -initRightMenu STATS (数值) tab label"),
    (0x0CFAF0, "ZFZombieMenu -initRightMenu ABILITY (能力) tab label"),
    (0x0D0582, "ZFZombieMenu -initStatDisplay POWER (力量) caption"),
    (0x0D05D2, "ZFZombieMenu -initStatDisplay LIFE (生命) caption"),
    (0x0D061C, "ZFZombieMenu -initStatDisplay SPEED (速度) caption"),
]

a = Annotator(load("zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v21fix.ipa"))
sl = a.sl
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

print("== call sites ==")
for addr, note in SITES:
    o = sl.addr_to_file(addr)
    raw = sl.data[o:o + 4]
    ins = list(md.disasm(raw, addr))
    txt = ("%s %s" % (ins[0].mnemonic, ins[0].op_str)) if ins else "<bad>"
    print("  %#010x  %s  %-24s %s" % (addr, raw.hex(), txt, note))

print("\n== setColor: selector value ==")
val = None
for slot, name in a.sel_at.items():
    if name == "setColor:":
        val = a._u32(slot)
        print("  selref slot %#x -> %#x  (%r)" % (slot, val, a.cstr(val)))
        break

print("\n== cave bytes 0x1138b8..0x113910 (current) ==")
o = sl.addr_to_file(0x1138B8)
b = sl.data[o:o + 0x58]
for k in range(0, len(b), 16):
    print("  %#010x  %s" % (0x1138B8 + k, b[k:k + 16].hex(" ")))

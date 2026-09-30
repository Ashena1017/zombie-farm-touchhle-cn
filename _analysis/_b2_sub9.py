"""Locate the sub9 materialisation sites for the three CFStrings by searching for
their movw/movt pairs directly (the generic tracker loses the register in a few
places, this is the ground truth)."""
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v14fix.ipa"

# (sub, CFString object address, label)
TARGETS = [
    (9, 0x3A68D0, "'%@ Used!'"),
    (9, 0x3A4A60, "'%@ (%i)            '"),
    (9, 0x3A4680, "'%@ (%i)        '"),
    (6, 0x46A940, "'%@ Used!'"),
    (6, 0x468AD0, "'%@ (%i)            '"),
    (6, 0x4686F0, "'%@ (%i)        '"),
]

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub, target, label in TARGETS:
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    txt = next(s for s in sl.sections if s.name == "__text")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    ins = list(md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr))
    lo = target & 0xFFFF
    hi = (target >> 16) & 0xFFFF
    print("\n=== sub%d  %s  (object %#x) ===" % (sub, label, target))
    found = 0
    if thumb:
        for i, x in enumerate(ins):
            if x.mnemonic == "movw" and x.operands and \
                    x.operands[-1].type == ARM_OP_IMM and x.operands[-1].imm == lo:
                for j in range(i + 1, min(i + 4, len(ins))):
                    y = ins[j]
                    if y.mnemonic == "movt" and y.operands and \
                            y.operands[-1].type == ARM_OP_IMM and \
                            y.operands[-1].imm == hi and \
                            y.operands[0].reg == x.operands[0].reg:
                        found += 1
                        print("   %#010x movw/movt r%d" % (x.address, x.operands[0].reg))
                        for t in ins[j + 1:j + 10]:
                            print("        %#010x %-8s %s" % (t.address, t.mnemonic, t.op_str))
                        break
    else:
        # ARM: a literal in __text holding the absolute address
        import struct
        for k in range(txt.size // 4):
            a = txt.addr + k * 4
            o = sl.addr_to_file(a)
            v = struct.unpack_from("<I", sl.data, o)[0]
            if v == target:
                found += 1
                print("   literal @ %#010x" % a)
        # and the delta idiom: literal D with (consume+8)+D == target
        for k in range(txt.size // 4):
            a = txt.addr + k * 4
            o = sl.addr_to_file(a)
            v = struct.unpack_from("<I", sl.data, o)[0]
            for cons in (a - 4, a - 8):
                if ((cons + 8 + v) & 0xFFFFFFFF) == target:
                    found += 1
                    print("   delta literal @ %#010x consumed by %#010x" % (a, cons))
    print("   -> %d site(s)" % found)

"""Does any code reference the *cstring* addresses directly (not via a CFString
object)?  sub9 has a '%@ Used!' CFString with no code reference, which is
suspicious - check the raw C string too."""
import bisect
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import classes_by_name, all_methods  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from capstone.arm_const import ARM_OP_IMM, ARM_OP_REG, ARM_REG_PC  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v15fix.ipa"
# CFString object -> cstring address (from the earlier scan)
PAIRS = {9: [(0x3A68D0, 0x2FD953, "'%@ Used!'"),
             (0x3A4A60, 0x2FA64F, "'%@ (%i)            '")],
         6: [(0x46A940, 0x3C1953, "'%@ Used!'")]}

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub, items in PAIRS.items():
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    thumb = sub == 9
    txt = next(s for s in sl.sections if s.name == "__text")
    cb = classes_by_name(sl)
    full = {}
    for cn, (c, info) in cb.items():
        for m in all_methods(sl, c, info):
            if m.imp:
                full.setdefault(m.imp & ~1, []).append(cn + " " + m.selector)
    starts = sorted(full)

    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        return "%s+%#x" % (full[starts[i]][0], a - starts[i]) if i >= 0 else "?"

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    print("\n#### sub%d" % sub)
    ins = list(md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr))
    for obj, csaddr, label in items:
        wanted = {obj, csaddr}
        print("   %s  object=%#x cstring=%#x" % (label, obj, csaddr))
        found = 0
        for i, x in enumerate(ins):
            ops = x.operands if x.id else []
            if not ops:
                continue
            m = x.mnemonic.split(".")[0]
            # ARM delta idiom: add rD, pc, rX  /  Thumb: add rD, pc
            if m == "add" and ops[0].type == ARM_OP_REG and len(ops) >= 2 and \
                    ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
                src = ops[2].reg if (not thumb and len(ops) == 3 and
                                     ops[2].type == ARM_OP_REG) else ops[0].reg
                # find the producer of src in the previous 6 instructions
                for j in range(max(0, i - 6), i):
                    y = ins[j]
                    yo = y.operands if y.id else []
                    if not yo or yo[0].type != ARM_OP_REG or yo[0].reg != src:
                        continue
                    if y.mnemonic in ("movw",) and yo[-1].type == ARM_OP_IMM:
                        imm = yo[-1].imm
                        for k in range(j + 1, i):
                            z = ins[k]
                            zo = z.operands if z.id else []
                            if z.mnemonic == "movt" and zo and zo[0].type == ARM_OP_REG \
                                    and zo[0].reg == src and zo[-1].type == ARM_OP_IMM:
                                val = ((zo[-1].imm & 0xFFFF) << 16) | (imm & 0xFFFF)
                                base = ((x.address + 4) & ~3) if thumb else (x.address + 8)
                                if base + val in wanted:
                                    found += 1
                                    print("      %#010x -> %#x  (%s)"
                                          % (x.address, base + val, owner(x.address)))
                                    for t in ins[max(0, i - 8):i + 6]:
                                        print("           %#010x %-8s %s"
                                              % (t.address, t.mnemonic, t.op_str))
                                    break
                    elif y.mnemonic == "ldr" and yo[1].type == 3 and yo[1].mem.base == ARM_REG_PC:
                        lit = (y.address + (4 if thumb else 8)) + (yo[1].mem.disp or 0)
                        o = sl.addr_to_file(lit)
                        if o:
                            val = struct.unpack_from("<I", sl.data, o)[0]
                            if val in wanted:
                                found += 1
                                print("      delta literal %#x = %#x consumed at %#010x (%s)"
                                      % (lit, val, x.address, owner(x.address)))
                                for t in ins[max(0, i - 8):i + 6]:
                                    print("           %#010x %-8s %s"
                                          % (t.address, t.mnemonic, t.op_str))
                    break
        print("      -> %d site(s)" % found)

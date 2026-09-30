"""Decode the tag -> ability-name jump table in -getRandomAbilityToUnlock (sub6)
and check the mapping is consistent (no off-by-one)."""

# --- project root bootstrap (added by _analysis/relocate_paths.py) ----------
import pathlib as _pl
import sys as _sys


def _find_project_root(start):
    for _p in [start, *start.parents]:
        if (_p / "tools" / "audit_zfr_ipa.py").exists():
            return _p
    raise RuntimeError("project root not found above %s" % start)


_PROJECT_ROOT = _find_project_root(_pl.Path(__file__).resolve().parent)
_sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
# ---------------------------------------------------------------------------
import sys, zipfile, struct
pass  # sys.path handled by the bootstrap below
from capstone import *
from capstone.arm_const import *
from audit_zfr_ipa import parse_fat

IPA = sys.argv[1] if len(sys.argv) > 1 else \
    str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v13fix.ipa")
TABLE = 0xB7334
N = 25
HANDLER_LO, HANDLER_HI = 0xB7398, 0xB74A0

with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)

    def u32(a):
        o = sl.addr_to_file(a)
        return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]

    def cs_(a):
        o = sl.addr_to_file(a)
        if o is None:
            return None
        try:
            e = sl.data.index(b"\0", o, o + 300)
        except ValueError:
            return None
        try:
            return sl.data[o:e].decode("utf-8")
        except Exception:
            return None

    CS2STR = {}
    for sec in sl.sections:
        if sec.name != "__cstring":
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        p = 0
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            try:
                CS2STR[sec.addr + p] = blob[p:e].decode("utf-8")
            except Exception:
                pass
            p = e + 1

    print("\n########## sub%d" % sub)
    if sub == 6:
        table_base = TABLE
    else:
        print("  (sub9 uses a different construction; skipped here)")
        continue

    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    # walk the handler chain: each handler is `ldr r0,[pc,#imm]` / `add r5,pc,r0` / `b 0xb74a0`
    # collect in address order, plus the CFString each materialises
    names_in_order = []
    a = HANDLER_LO
    while a < HANDLER_HI:
        ins = list(md.disasm(sl.data[sl.addr_to_file(a):sl.addr_to_file(a) + 12], a))
        if not ins:
            a += 4
            continue
        # resolve
        got = None
        regs = {}
        for i in ins:
            ops = i.operands
            if i.mnemonic == "ldr" and len(ops) == 2 and ops[1].type == ARM_OP_MEM and ops[1].mem.base == ARM_REG_PC:
                lit = i.address + 8 + (ops[1].mem.disp or 0)
                v = u32(lit)
                # delta relative to the *add* instruction; try both
                regs[ops[0].reg] = v
            elif i.mnemonic == "add" and len(ops) == 3 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC and ops[2].type == ARM_OP_REG:
                base = i.address + 8
                d = regs.get(ops[2].reg)
                if d is not None:
                    eff = (base + d) & 0xffffffff
                    got = eff
        if got is not None:
            # got is the address of a CFString object: data field is at +8
            d = u32(got + 8)
            names_in_order.append((a, got, CS2STR.get(d) if d else None))
        # advance to next handler: find the `b 0xb74a0`
        for i in ins:
            if i.mnemonic == "b" and int(i.op_str.lstrip('#'), 0) == 0xB74A0:
                a = i.address + 4
                break
        else:
            a += 4
            continue
        if a == 0xB74A0:
            break

    print("  handlers (address order):")
    for addr, eff, nm in names_in_order:
        print("     %#010x -> %#010x  %r" % (addr, eff, nm))

    print("\n  jump table @ %#x:" % table_base)
    tag_names = {}
    for i in range(N):
        e = u32(table_base + i * 4)
        target = (table_base + e) & 0xffffffff
        nm = None
        for addr, eff, n2 in names_in_order:
            if addr == target:
                nm = n2
        tag = 0x10 + i
        tag_names[tag] = nm
        print("     tag %#04x (idx %2d) -> %#010x  %r" % (tag, i, target, nm))

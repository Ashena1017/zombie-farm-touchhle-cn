"""Inspect the seasonal-quest machinery: addSeasonalQuests / checkSeason / removeSeasonalQuests."""

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
import sys, pathlib, struct, zipfile
pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

IPA = pathlib.Path(__file__).resolve().parent / str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
with zipfile.ZipFile(IPA) as z:
    data = z.read("Payload/ZFR.app/ZFR")
sl = [s for s in parse_fat(data) if s.subtype == 6][0]


def u32(a):
    o = sl.addr_to_file(a)
    return struct.unpack_from("<I", sl.data, o)[0] if o is not None else None


def cstr(a):
    return sl.cstr(a) if a else None


selrefs = {}
for s in sl.sections:
    if s.name != "__objc_selrefs":
        continue
    for i in range(s.size // 4):
        a = s.addr + i * 4
        v = u32(a)
        if v:
            t = cstr(v)
            if t and not t.startswith("<addr"):
                selrefs[a] = t

# also classrefs + cfstrings for the seasonalDate keys
WANT = ("checkSeason", "addSeasonalQuests", "removeSeasonalQuests", "seasonalDate",
        "seasonal", "isSeasonal", "dateFromString:", "compare:", "NSCalendarDate",
        "currentDate", "dateWithString:", "timeIntervalSinceNow", "levelRequired")
slots = {a: t for a, t in selrefs.items() if t in WANT}
print("selref slots found:")
for a, t in sorted(slots.items(), key=lambda kv: kv[1]):
    print("  %#08x  %s" % (a, t))

text = next(s for s in sl.sections if s.name == "__text")
md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
md.detail = True
md.skipdata = True
code = sl.data[text.offset:text.offset + text.size]

# 1) find all `ldr rX,[pc,rY]`-built references to these slots and report the next bl
print("\n=== call sites ===")
regs = {}
for ins in md.disasm(code, text.addr):
    m, ops = ins.mnemonic, ins.op_str
    if m == "ldr" and "[pc," in ops:
        try:
            rt = ops.split(",")[0].strip()
            idx = ops.split("[pc,")[1].rstrip("]").strip()
            if not idx.startswith("#"):
                continue
            regs[rt] = ("mem", ins.address + 8 + int(idx.lstrip("#"), 0))
        except Exception:
            pass
    elif m == "add" and ", pc, " in ops:
        try:
            rt = ops.split(",")[0].strip()
            regs[rt] = ("val", ins.address + 8 + int(ops.split(", pc, ")[1].strip().lstrip("#"), 0))
        except Exception:
            pass
    if m == "bl" and "0x393fe0" in ops:
        for r in ("r1", "r2", "r3"):
            if r in regs and regs[r][0] == "mem" and regs[r][1] in slots:
                print("  %#08x  sel=%-24s via %s" % (ins.address, slots[regs[r][1]], r))
                break
    if m == "ldr" and "[pc," not in ops and ops.startswith("r"):
        rt = ops.split(",")[0].strip()
        if rt in regs:
            regs.pop(rt)
    elif m.startswith(("mov", "add", "sub", "and", "orr", "lsl", "lsr", "bic")) and ops.startswith("r"):
        rt = ops.split(",")[0].strip()
        if rt in regs and rt not in ops.split(",", 1)[1]:
            regs.pop(rt, None)
    elif m in ("bl", "blx"):
        for r in ("r0", "r1", "r2", "r3", "r12"):
            regs.pop(r, None)

# 2) disassemble addSeasonalQuests 0x16d4a4 and checkSeason
def dump(addr, n=90, label=""):
    print("\n=== %s @ %#08x ===" % (label, addr))
    o = sl.addr_to_file(addr)
    nbytes = n * 4
    for ins in md.disasm(sl.data[o:o + nbytes], addr):
        mark = ""
        if ins.mnemonic in ("bl",) and ins.op_str.startswith("#"):
            t = int(ins.op_str.lstrip("#"), 0)
            if t in selrefs:
                mark = ""
        print("  %#08x: %-8s %s" % (ins.address, ins.mnemonic, ins.op_str))

# locate checkSeason method start: search __text for a `ldr r1,[pc,rN]` referencing checkSeason slot
cs_slots = [a for a, t in slots.items() if t == "checkSeason"]
print("\ncheckSeason slot addrs:", [hex(x) for x in cs_slots])
as_slots = [a for a, t in slots.items() if t == "addSeasonalQuests"]
print("addSeasonalQuests slot addrs:", [hex(x) for x in as_slots])

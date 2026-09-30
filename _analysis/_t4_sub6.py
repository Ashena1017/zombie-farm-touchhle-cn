"""#4 v6: decode sub6 toolSelected: PIC idiom: ldr rX,[pc,#off] pointer -> selref/ivar offset."""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods, read_ivars

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v19fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")
sl = next(s for s in parse_fat(fat) if s.subtype == 6)


def u32(a):
    o = sl.addr_to_file(a)
    return None if o is None or o + 4 > len(sl.data) else struct.unpack_from("<I", sl.data, o)[0]


def cs_(a, limit=160):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + limit)
    except ValueError:
        return None
    try:
        s = sl.data[o:e].decode("utf-8")
    except Exception:
        return None
    return s if s and s.isprintable() else None


selref_range = (0x4578E8, 0x45DE04)
selname = {}
a = selref_range[0]
while a < selref_range[1]:
    v = u32(a)
    if v:
        t = cs_(v)
        if t and not t.startswith("<addr"):
            selname[a] = t
    a += 4
print("selrefs: %d" % len(selname))

cb = classes_by_name(sl)
c, info = cb["ZFToolManager"]
ivar_list = read_ivars(sl, info.get("ivars"))
print("ZFToolManager ivars:")
for iv in ivar_list:
    print("  +0x%x %s %s" % (iv["offset"], iv.get("type", "?"), iv["name"]))
c2, info2 = cb["ZFToolsLayer"]
ivar_list2 = read_ivars(sl, info2.get("ivars"))
off2name = {iv["offset"]: iv["name"] for iv in ivar_list2}

# the pool at 0x2bb50..: each entry is a pointer; deref tells sel or ivar-off
for a in (0x2BB50, 0x2BB58, 0x2BB5C, 0x2BB60, 0x2BB64, 0x2BB68, 0x2BB6C, 0x2BB70,
          0x2BC64, 0x2BC70, 0x2BC74, 0x2BC7C, 0x2BC78, 0x2BC8C, 0x2BC90):
    p = u32(a)
    if p is None:
        print("  %#x: <unmapped>" % a)
        continue
    tag = ""
    if p in selname:
        tag = "SEL " + selname[p]
    else:
        v = u32(p)
        if v is not None and v in selname:
            tag = "-> SEL " + selname[v] + " (pool entry holds selref addr)"
        elif v is not None and v <= 0x400:
            tag = "-> ivar offset %#x %s?" % (v, off2name.get(v, ""))
        else:
            s = cs_(p, 64)
            tag = "-> %#x CSTR %r?" % (v, s)
    print("  pool %#x: p=%#x  %s" % (a, p, tag))

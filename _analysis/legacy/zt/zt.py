"""Shared loader for the tooltip font investigation. Read-only."""
import sys, os, zipfile, struct, pickle
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.abspath(os.path.join(HERE, "..", "..", "..", "tools"))
sys.path.insert(0, TOOLS)
from audit_zfr_ipa import parse_fat  # noqa
from inspect_v3_facts import (EXECUTABLE, ROOT, all_methods, classes_by_name,  # noqa
                              method_starts, ascii_str, u32)
from capstone import *  # noqa
from capstone.arm_const import *  # noqa

IPA = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed.ipa'


def load():
    with zipfile.ZipFile(os.path.join(str(ROOT), IPA)) as z:
        fat = z.read(EXECUTABLE)
    sls = {}
    for sl in parse_fat(fat):
        sls[sl.subtype] = sl
    return sls


def md_for(sl):
    m = Cs(CS_ARCH_ARM, CS_MODE_THUMB if sl.subtype == 9 else CS_MODE_ARM)
    m.detail = True
    m.skipdata = True
    return m


def find_meth(sl, cls, sel):
    byname = classes_by_name(sl)
    if cls not in byname:
        return None
    c, info = byname[cls]
    for m in all_methods(sl, c, info):
        if m.selector == sel:
            return m
    return None


def meth_range(sl, imp, cap=0x1000):
    starts = method_starts(sl)
    s = imp & ~1
    nxt = next((x for x in starts if x > s), None)
    end = min(nxt, s + cap) if nxt else s + cap
    return s, end


def dis(sl, start, end, thumb=None):
    off = sl.addr_to_file(start)
    if off is None:
        return []
    if thumb is None:
        thumb = sl.subtype == 9
    m = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    m.detail = True
    m.skipdata = True
    return list(m.disasm(sl.data[off:off + (end - start)], start))


def rd(sl, addr, n):
    off = sl.addr_to_file(addr)
    if off is None:
        return None
    return sl.data[off:off + n]


def f32(b):
    return struct.unpack('<f', b)[0]


def f64(b):
    return struct.unpack('<d', b)[0]

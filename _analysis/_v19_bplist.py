"""v19 recon F: the fixed ZIP slot is 189 bytes but the repaired plist deflates to
193.  Build a deduplicated binary plist by hand (plistlib never shares identical
string objects) and see whether it fits.
"""
import plistlib
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v18fix.ipa"
NAME = "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings"


def int_obj(v):
    if v < 0x100:
        return b"\x10" + struct.pack(">B", v)
    if v < 0x10000:
        return b"\x11" + struct.pack(">H", v)
    return b"\x13" + struct.pack(">I", v)


def str_obj(s):
    try:
        b = s.encode("ascii")
        ascii_ = True
    except UnicodeEncodeError:
        b = s.encode("utf-16-be")
        ascii_ = False
    n = len(b) if ascii_ else len(s)
    head = bytes([(0x50 if ascii_ else 0x60) | n]) if n < 15 else \
        bytes([0x5F if ascii_ else 0x6F]) + int_obj(n)
    return head + b


def write_bplist(d):
    objs: list[bytes] = []
    refs: dict = {}

    def intern(key, blob):
        if key in refs:
            return refs[key]
        refs[key] = len(objs)
        objs.append(blob)
        return refs[key]

    items = sorted(d.items())
    # index 0 must be the dict; we need its refs before writing it, so reserve it
    objs.append(b"")
    krefs = [intern(("k", k), str_obj(k)) for k, _ in items]
    vrefs = [intern(("v", v), str_obj(v)) for _, v in items]
    body = bytes([0xD0 | len(items)]) + bytes(krefs) + bytes(vrefs)
    objs[0] = body

    out = bytearray(b"bplist00")
    offsets = []
    for o in objs:
        offsets.append(len(out))
        out += o
    off_size = 1 if len(out) < 0x100 else 2
    off_start = len(out)
    for off in offsets:
        out += struct.pack(">B" if off_size == 1 else ">H", off)
    out += b"\0" * 5 + bytes([0, off_size, 1])
    out += struct.pack(">QQQ", len(objs), 0, off_start)
    return bytes(out)


with zipfile.ZipFile(IPA) as z:
    member = z.read(NAME)
    truth = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
    table = plistlib.loads(member)


def deflate(d):
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(d) + co.flush()


fixed = {k: truth[k] for k in table}
mine = write_bplist(fixed)
print("hand-written plist : %d bytes -> deflate %d" % (len(mine), len(deflate(mine))))
rt = plistlib.loads(mine)
print("round-trip equal   : %s" % (rt == fixed))
print("plistlib's version : %d bytes -> deflate %d"
      % (len(plistlib.dumps(fixed, fmt=plistlib.FMT_BINARY)),
         len(deflate(plistlib.dumps(fixed, fmt=plistlib.FMT_BINARY)))))
print("orig member        : %d bytes -> deflate %d" % (len(member), len(deflate(member))))
print("SLOT               : 189")

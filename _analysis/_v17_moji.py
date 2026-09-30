"""v17 recon E: FULL mojibake sweep of every CFString and every __cstring in both
slices.  The v16 fix only covered four CFStrings that an earlier (buggy) scan had
already found; this asks the question again from scratch.

Mojibake signature: Latin Extended-A (U+0100..U+017F) -- the codex patch turned
byte pairs like (UTF-8 of CJK) into these.  A Chinese/English game has no
legitimate reason to use them.
"""
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v16fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")


def is_moji(t):
    return any(0x100 <= ord(c) <= 0x17F for c in t)


def read_cstr(sl, a, limit=400):
    o = sl.addr_to_file(a)
    if o is None:
        return None
    try:
        e = sl.data.index(b"\0", o, o + limit)
    except ValueError:
        return None
    try:
        return sl.data[o:e].decode("utf-8")
    except Exception:
        return None


for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)

    print("\n" + "#" * 78)
    print("# sub%d" % sub)
    print("#" * 78)

    # --- CFString objects ---------------------------------------------------
    n_cf = n_moji = 0
    for sec in sl.sections:
        if sec.name != "__cfstring":
            continue
        for off in range(0, sec.size - 16, 16):
            a = sec.addr + off
            flags = struct.unpack_from("<I", sl.data, sec.offset + off + 4)[0]
            if flags != 0x7C8:
                continue
            n_cf += 1
            data, size = struct.unpack_from("<II", sl.data, sec.offset + off + 8)
            t = read_cstr(sl, data)
            if t is None:
                t = read_cstr(sl, data)
            if t and is_moji(t):
                n_moji += 1
                print("   CFSTR %#010x size=%-3d data=%#010x  %r" % (a, size, data, t))
    print("   -- %d CFStrings, %d mojibake" % (n_cf, n_moji))

    # --- every NUL-terminated string in __cstring / __const / __ustring -----
    seen = set()
    for sec in sl.sections:
        if sec.name not in ("__cstring", "__const", "__ustring", "__objc_methname"):
            continue
        blob = sl.data[sec.offset:sec.offset + sec.size]
        p = 0
        while p < len(blob):
            e = blob.find(b"\0", p)
            if e < 0:
                break
            if e > p:
                try:
                    t = blob[p:e].decode("utf-8")
                except Exception:
                    t = None
                if t and is_moji(t) and len(t) < 90:
                    key = (sec.name, t)
                    if key not in seen:
                        seen.add(key)
                        print("   %-12s @%#010x  %r" % (sec.name, sec.addr + p, t))
            p = e + 1

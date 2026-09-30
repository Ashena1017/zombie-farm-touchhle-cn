"""v19 recon A: find the fertilize-action mojibake (图1).

Sweeps every .strings / .plist member of the app bundle plus the executable's
CFStrings for characters that Chinese text can never legitimately contain:
U+00A0..U+024F (Latin-1 supplement accents + Latin Extended-A/B).
"""
import plistlib
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v18fix.ipa"
BAD = lambda s: any(0x00A0 <= ord(c) <= 0x024F for c in s)          # noqa: E731
BADK = lambda s: any(0x0100 <= ord(c) <= 0x024F for c in s)         # noqa: E731

with zipfile.ZipFile(IPA) as z:
    names = z.namelist()
    print("== members that are .strings/.plist/executable ==")
    targets = [n for n in names if n.endswith((".strings", ".plist"))
               or n == "Payload/ZFR.app/ZFR"]
    targets = [n for n in targets if "lproj/" not in n or "zh-Han" in n]
    for n in targets:
        raw = z.read(n)
        try:
            pl = plistlib.loads(raw)
        except Exception:
            pl = None
        if isinstance(pl, dict):
            bad = [(k, v) for k, v in pl.items() if isinstance(v, str) and BAD(v)]
            badk = [k for k in pl if isinstance(k, str) and BADK(k)]
            if bad or badk:
                print("\n  %s   (%d entries)" % (n, len(pl)))
                for k, v in bad:
                    print("     VALUE %-46r -> %r" % (k, v))
                for k in badk:
                    print("     KEY   %r -> %r" % (k, pl[k]))
        else:
            # raw byte scan for Latin Extended-A encoded as UTF-8 (0xC4 80..0xC5 BF)
            hits = []
            i = 0
            while i < len(raw) - 1:
                if raw[i] == 0xC4 and 0x80 <= raw[i + 1] <= 0xBF or \
                   raw[i] == 0xC5 and 0x80 <= raw[i + 1] <= 0xBF:
                    s = max(0, i - 28)
                    hits.append((i, raw[s:i + 8]))
                    i += 2
                else:
                    i += 1
            if hits:
                print("\n  %s   (%d Latin-Extended runs)" % (n, len(hits)))
                for off, ctx in hits[:12]:
                    print("     @%#x %r" % (off, ctx))

    # ---- the executable -----------------------------------------------
    fat = z.read("Payload/ZFR.app/ZFR")

print("\n\n== executable CFStrings with Latin-1/Latin-Extended ==")
for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)

    def cstr(a, limit=400):
        o = sl.addr_to_file(a)
        if o is None:
            return None
        e = sl.data.find(b"\0", o, o + limit)
        if e < 0:
            return None
        try:
            return sl.data[o:e].decode("utf-8")
        except Exception:
            return None

    sec = next(s for s in sl.sections if s.name == "__cfstring")
    n = 0
    for off in range(0, sec.size - 16, 16):
        flags = struct.unpack_from("<I", sl.data, sec.offset + off + 4)[0]
        if flags != 0x7C8:
            continue
        data, size = struct.unpack_from("<II", sl.data, sec.offset + off + 8)
        t = cstr(data)
        if t and BAD(t):
            n += 1
            print("   sub%d CFSTR %#010x size=%-3d %r" % (sub, sec.addr + off, size, t))
    print("   sub%d: %d mojibake CFStrings" % (sub, n))

"""Batch-2 post-test diagnostics.

#1 still English  -> was the sub6-only retarget simply not the executed slice?
#5 still '+200eE' -> where does the mojibake still live?
#3 count wrong    -> what exactly is the %i argument at each label site?
"""
import collections
import struct
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())

# The emulator lives in its own folder now (the tree mirrors the shipped ./Release
# layout). Fall back to the flat layout so this keeps working either way.
_HLE = ROOT / "touchHLE"
if not (_HLE / "touchHLE.exe").exists():
    _HLE = ROOT

sys.path.insert(0, str(ROOT / "tools"))

IPA = ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v15fix.ipa"

print("=" * 78)
print("1) what was actually launched?")
print("=" * 78)
fp = _HLE / "zfr_last_launch.txt"
print(fp.read_text(encoding="utf-8").strip() if fp.exists() else "  (missing)")

print()
print("=" * 78)
print("2) duplicate ZIP entries?")
print("=" * 78)
with zipfile.ZipFile(IPA) as z:
    names = z.namelist()
    dupes = [n for n, c in collections.Counter(names).items() if c > 1]
    print("   entries: %d, duplicates: %s" % (len(names), dupes or "none"))

print()
print("=" * 78)
print("3) where does the mojibake still live?")
print("=" * 78)
PATTERNS = {
    "UTF-8  ėĚ (U+0117 U+011A)": "ėĚ".encode("utf-8"),
    "UTF-8  Ęę (U+0118 U+0119)": "Ęę".encode("utf-8"),
    "UTF-16BE ėĚ": "ėĚ".encode("utf-16-be"),
    "UTF-16BE Ęę": "Ęę".encode("utf-16-be"),
}
with zipfile.ZipFile(IPA) as z:
    for n in sorted(z.namelist()):
        if n.endswith("/"):
            continue
        try:
            d = z.read(n)
        except Exception:
            continue
        for label, pat in PATTERNS.items():
            start = 0
            hits = []
            while True:
                i = d.find(pat, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + 1
            if not hits:
                continue
            # printable context for each hit
            print("   %-58s %-26s x%d" % (n, label, len(hits)))
            for i in hits[:4]:
                lo, hi = max(0, i - 40), min(len(d), i + 60)
                ctx = d[lo:hi]
                for enc in ("utf-8", "utf-16-be", "latin1"):
                    try:
                        s = ctx.decode(enc)
                        if any('\u4e00' <= c <= '\u9fff' for c in s):
                            print("        @%#x  %r" % (i, s))
                            break
                    except Exception:
                        continue

print()
print("=" * 78)
print("4) the tool-label sites, with the stack argument")
print("=" * 78)
from audit_zfr_ipa import parse_fat  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402

with zipfile.ZipFile(IPA) as zz:
    fat = zz.read("Payload/ZFR.app/ZFR")

SITES = {6: [(0x2BAF8, "toolSelected: (was correct in Chinese)"),
             (0x3371C, "onTileClickUp:forTool: #1 (patched)"),
             (0x33A34, "onTileClickUp:forTool: #2 (patched)")],
         9: [(0x212D0, "toolSelected: (was correct in Chinese)"),
             (0x26D90, "onTileClickUp:forTool: (patched)")]}
for sub, sites in SITES.items():
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if sub == 9 else CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    for addr, note in sites:
        print("\n   --- sub%d %#x  %s ---" % (sub, addr, note))
        o = sl.addr_to_file(addr)
        ins = list(md.disasm(sl.data[o - 48:o + 40], addr - 48))
        for i in ins:
            mark = "   <<< CALL" if i.address == addr else ""
            print("      %#010x  %-9s %s%s" % (i.address, i.mnemonic, i.op_str, mark))

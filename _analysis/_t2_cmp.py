"""Compare the label factories of one method between the untouched baseline IPA
and the current build, so we can tell an original font size from an edited one.

    python _t2_cmp.py CLASS SELECTOR [CLASS SELECTOR ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

IPA = sys.argv[1] if sys.argv[1].endswith(".ipa") else None
rest = sys.argv[2:] if IPA else sys.argv[1:]
WANT = ("labelWithString:fontName:fontSize:",
        "labelWithString:dimensions:alignment:fontName:fontSize:",
        "bitmapFontAtlasWithString:fntFile:")

a = Annotator(load(IPA))
for i in range(0, len(rest), 2):
    cls, sel = rest[i], rest[i + 1]
    print("### %s -%s" % (cls, sel))
    _m, start, end = a.method_range(cls, sel)
    if start is None:
        print("   NOT FOUND")
        continue
    for x, ann, _ in a.annotate(a.disasm(start, end)):
        if not ann.startswith("MSG "):
            continue
        nm = ann[4:].split("(", 1)[0]
        if nm not in WANT:
            continue
        parts = ann.split("(", 1)[1].rstrip(")").split(", ")
        size = ""
        for p in parts:
            if p.startswith("sp+0x0=") and nm == "labelWithString:fontName:fontSize:":
                size = p
            if p.startswith("sp+0xc=") and "dimensions" in nm:
                size = p
        print("   %#010x  %-52s font=%s" % (x.address, nm, size or "?"))

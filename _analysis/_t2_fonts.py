"""Report every label-factory / setColor call in one class's methods, with the
resolved fontSize slot (3-arg factory -> [sp], 5-arg factory -> [sp+0xc]).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

CLS = sys.argv[1]
SEL_FILTER = sys.argv[2:] or None
WANT = {"labelWithString:fontName:fontSize:",
        "labelWithString:dimensions:alignment:fontName:fontSize:",
        "bitmapFontAtlasWithString:fntFile:",
        "setColor:", "setFontSize:", "initWithString:fontName:fontSize:",
        "alertWindowSlideInInformative:withMessage:withSprite:withHudFile:"
        "withButtonRect:withButtonSelectedRect:withButtonText:withButtonColor:slideFromLeft:",
        "makeWindow:corner:bar:file:color:bcorner:bbar:side:"}

a = Annotator(load())
for _s, sel, _m in a.ordered_methods(CLS):
    if SEL_FILTER and not any(f in sel for f in SEL_FILTER):
        continue
    _mm, start, end = a.method_range(CLS, sel)
    if start is None:
        continue
    rows = a.annotate(a.disasm(start, end))
    hits = []
    for x, ann, _ in rows:
        if not ann.startswith("MSG "):
            continue
        nm = ann[4:].split("(", 1)[0]
        if nm not in WANT:
            continue
        args = ann.split("(", 1)[1].rstrip(")")
        parts = [p for p in args.split(", ")]
        head = ", ".join(parts[:3])
        slot = ""
        for p in parts:
            if p.startswith("sp+0x0=") and nm == "labelWithString:fontName:fontSize:":
                slot = p
            if p.startswith("sp+0xc=") and "dimensions" in nm:
                slot = p
        hits.append((x.address, nm, head, slot))
    if hits:
        print("### %s -%s  (%#x..%#x)" % (CLS, sel, start, end))
        for addr, nm, head, slot in hits:
            print("   %#010x  %-52s (%s)  %s" % (addr, nm, head, slot))
        print()

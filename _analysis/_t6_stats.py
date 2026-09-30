"""#7 / #8 recon: where do STATS/ABILITY/POWER/LIFE/SPEED labels come from, and
which label carries the 陵墓 (Mausoleum) button caption?

Scans every ZFZombieMenu / ZFMausoleumMenu method (sub9, the live slice) and reports
  * CFString mentions of the five stat captions + 'Mausoleum'
  * setColor: / setFontSize: / label factories with resolved arguments

Writes to the path given as argv[1] (default _t6_stats.out.txt next to this file)
so PowerShell never has to render the huge annotations inline.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load
from inspect_v3_facts import all_methods

TARGET_CF = {"STATS", "ABILITY", "POWER", "LIFE", "SPEED", "Mausoleum",
             "Mausoleum 1", "Mausoleum 2", "Mausoleum 3", "STORAGE TABS"}
WANT_MSG = {"setColor:", "setFontSize:", "setString:",
            "labelWithString:fontName:fontSize:",
            "labelWithString:dimensions:alignment:fontName:fontSize:",
            "bitmapFontAtlasWithString:fntFile:",
            "setPosition:", "setAnchorPoint:"}

CLASSES = ["ZFZombieMenu", "ZFMausoleumMenu"]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("_t6_stats.out.txt")

a = Annotator(load())
lines = []


def emit(s=""):
    lines.append(s)


for cls_name in CLASSES:
    for start0, sel, _m in a.ordered_methods(cls_name):
        _, start, end = a.method_range(cls_name, sel)
        if start is None:
            continue
        hits = []
        for x, ann, _ in a.annotate(a.disasm(start, end)):
            if ann.startswith("CFSTR "):
                if ann[7:-1] in TARGET_CF:
                    hits.append((x.address, ann))
            elif ann.startswith("MSG "):
                nm = ann[4:].split("(", 1)[0]
                if nm in WANT_MSG:
                    # trim the noisy stack dump to the first 12 entries
                    args = ann.split("(", 1)[1]
                    parts = args.rstrip(")").split(", ")
                    hits.append((x.address, "MSG " + nm + "(" + ", ".join(parts[:14]) + ")"))
        if hits:
            emit("### %s -%s  (%#x..%#x)" % (cls_name, sel, start, end))
            for addr, ann in hits:
                emit("   %#010x  %s" % (addr, ann))
            emit()


def clean(s):
    return "".join(c if (c.isprintable() or c in " \n") else "\\x%02x" % ord(c) for c in s)


OUT.write_text(clean("\n".join(lines)) + "\n", encoding="utf-8")
print("wrote %s (%d lines)" % (OUT, len(lines)))

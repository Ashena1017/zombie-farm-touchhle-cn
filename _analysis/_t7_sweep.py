"""Global CFString-reference sweep (sub9) for the #7/#8 caption strings.

Walks every class/method of the live slice and reports each site that
materialises one of the target CFStrings, together with the message that
consumes it.  Output goes to a file so the console never renders it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

TARGETS = {"POWER", "LIFE", "SPEED", "STATS", "ABILITY", "Mausoleum",
           "Store", "Retrieve", "Sell", "Mausoleum 1"}
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("_t7_sweep.txt")

a = Annotator(load())
lines = []
for cls_name in sorted(a.by_name):
    try:
        methods = a.ordered_methods(cls_name)
    except Exception as exc:                      # pragma: no cover
        lines.append("!! %s: %s" % (cls_name, exc))
        continue
    for _start, sel, _m in methods:
        _mm, start, end = a.method_range(cls_name, sel)
        if start is None:
            continue
        hits = []
        rows = a.annotate(a.disasm(start, end))
        for i, (x, ann, _) in enumerate(rows):
            if ann.startswith("CFSTR "):
                if ann[7:-1] in TARGETS:
                    hits.append((x.address, ann, i))
        if hits:
            lines.append("### %s -%s  (%#x..%#x)" % (cls_name, sel, start, end))
            for addr, ann, i in hits:
                lines.append("   %#010x  %s" % (addr, ann))
                for y, yann, _ in rows[i + 1:i + 26]:
                    if yann.startswith("MSG "):
                        args = yann.split("(", 1)[1]
                        parts = args.rstrip(")").split(", ")
                        lines.append("        -> %#010x  %s(%s)"
                                     % (y.address, yann[4:].split("(", 1)[0],
                                        ", ".join(parts[:10])))
            lines.append("")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote %s (%d lines)" % (OUT, len(lines)))

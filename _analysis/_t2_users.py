"""Find every message send of one selector across the live slice."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

NEEDLES = sys.argv[1:]
a = Annotator(load())
n = 0
for cls_name in sorted(a.by_name):
    for _s, sel, _m in a.ordered_methods(cls_name):
        _mm, start, end = a.method_range(cls_name, sel)
        if start is None:
            continue
        for x, ann, _ in a.annotate(a.disasm(start, end)):
            if not ann.startswith("MSG "):
                continue
            nm = ann[4:].split("(", 1)[0]
            if nm in NEEDLES:
                print("%#010x  %s -%s  -> %s" % (x.address, cls_name, sel, nm))
                n += 1
print("total %d" % n, file=sys.stderr)

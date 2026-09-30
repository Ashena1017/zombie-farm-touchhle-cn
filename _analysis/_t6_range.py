"""Dump annotator output for arbitrary address ranges to a text file (so the
console never has to render it).  Usage:

    python _t6_range.py OUTFILE START END [START END ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

out_path = Path(sys.argv[1])
pairs = [int(v, 0) for v in sys.argv[2:]]
a = Annotator(load())
lines = []
for i in range(0, len(pairs), 2):
    lo, hi = pairs[i], pairs[i + 1]
    lines.append("==== range %#x..%#x ====" % (lo, hi))
    for x, ann, _ in a.annotate(a.disasm(lo, hi)):
        lines.append("  %#010x  %-8s %-42s %s" % (x.address, x.mnemonic, x.op_str, ann))
    lines.append("")
out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote %s (%d lines)" % (out_path, len(lines)))

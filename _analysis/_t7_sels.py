"""List selectors of interest (label factories / colour helpers)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

a = Annotator(load())
for n in sorted(set(a.sel_cstr.values())):
    low = n.lower()
    if "label" in low or "black" in low or "fontsize" in low:
        print("  ", n)

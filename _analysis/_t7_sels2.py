"""List selectors containing colour-ish tokens."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

a = Annotator(load())
for n in sorted(set(a.sel_cstr.values())):
    if "color" in n.lower() or "Color" in n:
        print("  ", n)

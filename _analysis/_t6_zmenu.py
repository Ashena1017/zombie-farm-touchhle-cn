"""#7/#8 recon: dump ZFZombieMenu stat-display + element setup methods with full
CFString/SEL/float annotation (sub9 = the live slice)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _t6_ann import Annotator, load

a = Annotator(load())

WANT = [
    ("ZFZombieMenu", "initStatDisplay"),
    ("ZFZombieMenu", "displayStatBarWithTotalValue:pos:withParent:"),
    ("ZFZombieMenu", "displayStats:"),
    ("ZFZombieMenu", "initAbilitiesDisplay"),
    ("ZFZombieMenu", "cleanStatDisplay"),
    ("ZFZombieMenu", "initElements"),
    ("ZFZombieMenu", "displayPage:"),
]

only = sys.argv[1:] if len(sys.argv) > 1 else None
for cls, sel in WANT:
    if only and not any(o in sel for o in only):
        continue
    a.dump_method(cls, sel)

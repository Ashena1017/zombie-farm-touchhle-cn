"""Dump the segment/section layout of both slices, showing gaps (potential free space)."""

# --- project root bootstrap (added by _analysis/relocate_paths.py) ----------
import pathlib as _pl
import sys as _sys


def _find_project_root(start):
    for _p in [start, *start.parents]:
        if (_p / "tools" / "audit_zfr_ipa.py").exists():
            return _p
    raise RuntimeError("project root not found above %s" % start)


_PROJECT_ROOT = _find_project_root(_pl.Path(__file__).resolve().parent)
_sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
# ---------------------------------------------------------------------------
import sys, zipfile, struct
pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

for sub in (6, 9):
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    print("\n########## sub%d ##########" % sub)
    secs = sorted(sl.sections, key=lambda s: s.addr)
    prev_end = None
    prev_name = None
    for s in secs:
        gap = ""
        if prev_end is not None and s.addr > prev_end:
            gap = "   <<< GAP %d bytes (%#x..%#x)" % (s.addr - prev_end, prev_end, s.addr)
        print("  %-24s addr=%#010x size=%-9d off=%#010x%s" % (s.name, s.addr, s.size, s.offset, gap))
        prev_end = s.addr + s.size
        prev_name = s.name
    if sl.sections:
        last = secs[-1]
        print("  (slice data len %d)" % len(sl.data))

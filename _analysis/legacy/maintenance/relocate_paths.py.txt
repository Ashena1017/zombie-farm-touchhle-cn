"""Rewrite the moved _analysis/ scripts so they locate the project root from
their own __file__ instead of assuming the current working directory.

Run once after the reorganisation; it is idempotent (a script that already has
the bootstrap is skipped).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "_analysis"

BOOTSTRAP = '''
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
'''

MARK = "_find_project_root"

changed = []
for p in sorted(AN.glob("*.py")):
    if p.name == Path(__file__).name:
        continue
    src = p.read_text(encoding="utf-8")
    if MARK in src:
        continue
    orig = src

    # absolute-path forms first
    src = src.replace('str(Path(__file__).resolve().parent / "tools")',
                      'str(_PROJECT_ROOT / "tools")')
    src = src.replace('str(pathlib.Path(__file__).resolve().parent / "tools")',
                      'str(_PROJECT_ROOT / "tools")')
    src = src.replace('Path(__file__).resolve().parent / "zombie_farm_ipa"',
                      '_PROJECT_ROOT / "zombie_farm_ipa"')
    src = src.replace('pathlib.Path(__file__).resolve().parent / "zombie_farm_ipa"',
                      '_PROJECT_ROOT / "zombie_farm_ipa"')

    # cwd-relative sys.path hacks -> handled by the bootstrap
    src = re.sub(r'^sys\.path\.insert\(0,\s*["\']tools["\']\)\s*$',
                 'pass  # sys.path handled by the bootstrap below', src, flags=re.M)
    src = re.sub(r'^sys\.path\.insert\(0,\s*str\(_PROJECT_ROOT / "tools"\)\)\s*$',
                 'pass  # sys.path handled by the bootstrap below', src, flags=re.M)

    # cwd-relative project paths in string literals
    src = re.sub(r'(["\'])zombie_farm_ipa/([^"\']*)\1',
                 lambda m: 'str(_PROJECT_ROOT / "zombie_farm_ipa/%s")' % m.group(2), src)

    if src == orig:
        continue

    # insert the bootstrap after any __future__ import / module docstring
    lines = src.splitlines(keepends=True)
    idx = 0
    if lines and lines[0].lstrip().startswith(('"""', "'''")):
        q = lines[0].lstrip()[:3]
        if lines[0].count(q) >= 2:
            idx = 1
        else:
            for j in range(1, len(lines)):
                if q in lines[j]:
                    idx = j + 1
                    break
    for j in range(idx, min(idx + 6, len(lines))):
        if lines[j].startswith("from __future__"):
            idx = j + 1
    out = "".join(lines[:idx]) + BOOTSTRAP + "".join(lines[idx:])
    p.write_text(out, encoding="utf-8")
    changed.append(p.name)

print("rewrote %d script(s):" % len(changed))
for n in changed:
    print("   " + n)
sys.exit(0)

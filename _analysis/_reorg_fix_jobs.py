#!/usr/bin/env python3
r"""Repair scripts where the $hleRoot definition landed in the wrong scope.

`_reorg_fix_paths.py` chose the insertion point as "just after the first top-level
param() block", found by scanning for the first `^\s*param\s*\(`. That is wrong for
scripts whose first `param(...)` belongs to a **scriptblock passed to Start-Job**:
the definition lands inside the job, where `$root` is not bound, and the job is
still handed `$root` as its working directory.

The reliable signal is order of appearance: if `$hleRoot` is *used* before the line
that *defines* it, the definition is in the wrong place. (The indentation is not a
signal -- the misplaced block sits at column 0 too.)

Fix, per affected script:
  * delete the misplaced definition;
  * re-insert it at the top level, right after the first column-0 `$root = ...`;
  * rebase `-ArgumentList ..., $root` to `..., $hleRoot`, so the job's
    Set-Location gets the emulator folder rather than the repo root.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The definition block exactly as _reorg_fix_paths.py wrote it.
DEF_BLOCK = re.compile(
    r"(?:[ \t]*# The emulator lives in its own folder now \(the tree mirrors the shipped\n"
    r"[ \t]*# \./Release layout\)\. Fall back to the flat layout so these scripts keep working\n"
    r"[ \t]*# either way -- same rule GameManager\.ps1 uses\.\n)?"
    r"[ \t]*\$hleRoot = if \(Test-Path -LiteralPath \(Join-Path \$root 'touchHLE\\touchHLE\.exe'\)\) \{\n"
    r"[ \t]*Join-Path \$root 'touchHLE'\n"
    r"[ \t]*\} else \{\n"
    r"[ \t]*\$root\n"
    r"[ \t]*\}\n"
)

DEF = (
    "\n# The emulator lives in its own folder now (the tree mirrors the shipped\n"
    "# ./Release layout). Fall back to the flat layout so these scripts keep working\n"
    "# either way -- same rule GameManager.ps1 uses.\n"
    "$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\\touchHLE.exe')) {\n"
    "    Join-Path $root 'touchHLE'\n"
    "} else {\n"
    "    $root\n"
    "}\n"
)

TOP_ROOT = re.compile(r"^\$(root|Root)[ \t]*=[^\n]*$", re.MULTILINE)
ARGLIST = re.compile(r"(-ArgumentList\s+[^\n]*?),\s*\$(root|Root)\s*$", re.MULTILINE)


def repair(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    d = DEF_BLOCK.search(text)
    if d is None:
        return text, notes

    # First *use* of $hleRoot outside the definition itself.
    rest = text[: d.start()] + text[d.end() :]
    use = re.search(r"\$hleRoot\b", rest)
    if use is None or use.start() > d.start():
        return text, notes            # defined before first use: already correct

    notes.append("definition was below its first use")

    text = text[: d.start()] + text[d.end() :]

    m = TOP_ROOT.search(text)
    if m is None:
        raise SystemExit("  !! no column-0 $root assignment to anchor to")
    text = text[: m.end()] + "\n" + DEF + text[m.end() :]
    notes.append("moved to top level")

    new, n = ARGLIST.subn(r"\1, $hleRoot", text)
    if n:
        text = new
        notes.append(f"-ArgumentList -> $hleRoot ({n})")

    return text, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    changed = 0
    for path in sorted((ROOT / "_analysis").glob("*.ps1")):
        text = path.read_text(encoding="utf-8")
        new, notes = repair(text)
        if not notes:
            continue
        print(f"  {path.name}: {', '.join(notes)}")
        if args.apply:
            path.write_text(new, encoding="utf-8")
        changed += 1

    print()
    print(f"{'repaired' if args.apply else 'would repair'}: {changed}")
    if not args.apply:
        print("(dry run -- pass --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

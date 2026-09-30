#!/usr/bin/env python3
r"""Point the analysis/launcher scripts at the new <root>\touchHLE\ folder.

After `_reorg_touchhle.py` moved the emulator into `<root>\touchHLE\`, every script
that built a path as `Join-Path $root 'touchHLE.exe'` (or `_build_tools`,
`touchHLE-fork`, `touchHLE-trunk`, `touchHLE_sandbox`, ...) resolves to a file that
no longer exists.

The fix is uniform and deliberately boring: introduce one variable per script that
holds the emulator folder, then rebase those paths onto it.

    $hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
        Join-Path $root 'touchHLE'
    } else {
        $root          # older layout: emulator files sat next to the script
    }

Both layouts stay supported, exactly like GameManager.ps1 does it, so the scripts
keep working if the folder is ever flattened again.

The variable is called `$hleRoot` rather than `$hle` because several scripts already
use `$hle` for the *executable* (`$hle = Join-Path $Root 'touchHLE_fork.exe'`).

Idempotent: a script that already contains `$hleRoot =` is left alone.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Things that live under <root>\touchHLE\ now.
HLE_PREFIXES = (
    "touchHLE.exe", "touchHLE_fork.exe", "touchHLE.exe.backup",
    "touchHLE_dylibs", "touchHLE_fonts", "touchHLE_sandbox",
    "touchHLE_options.txt", "touchHLE_default_options.txt",
    "touchHLE_log.txt", "touchHLE_time_offset_seconds.txt",
    "touchHLE-fork", "touchHLE-trunk", "_build_tools",
    "zfr_last_launch.txt", "zfr_last_run.log",
)

# `Join-Path $root 'touchHLE...'` / `Join-Path $Root "_build_tools..."`
JOIN = re.compile(
    r"Join-Path\s+\$(root|Root)\s+(['\"])(?P<rel>" +
    "|".join(re.escape(p) for p in HLE_PREFIXES) + r")",
)

# `Get-ChildItem $root -Filter 'touchHLE.exe.backup...'`
GCI = re.compile(
    r"Get-ChildItem\s+\$(root|Root)\s+-Filter\s+(['\"])(?P<rel>touchHLE\.exe\.backup)",
)

# `$Root\touchHLE_sandbox\...` used as a bare string (no Join-Path).
BARE = re.compile(
    r"\$(root|Root)\\(?P<rel>touchHLE_[A-Za-z_]+|touchHLE\.exe|_build_tools)",
)

# Python scripts do it with pathlib: `ROOT / "touchHLE.exe"`. They get a
# module-level HLE constant plus a rebase of the literals.
PY = re.compile(
    r"(?P<var>[A-Za-z_][A-Za-z_0-9]*)\s*/\s*(?P<q>['\"])(?P<rel>" +
    "|".join(re.escape(p) for p in HLE_PREFIXES) + r")(?P=q)",
)

PY_CONST = '''
# The emulator lives in its own folder now (the tree mirrors the shipped ./Release
# layout). Fall back to the flat layout so this keeps working either way.
_HLE = ROOT / "touchHLE"
if not (_HLE / "touchHLE.exe").exists():
    _HLE = ROOT
'''


def _py_root_var(text: str) -> str | None:
    """Name of the variable holding the repo root in a Python script."""
    for cand in ("ROOT", "root"):
        if re.search(rf"^{cand}\s*=", text, re.MULTILINE):
            return cand
    return None

# Where to insert the $hleRoot definition.
#
# NOT simply "after the $root assignment": in many scripts $root is a [string]
# parameter, so its assignment line sits inside a param() block. Inserting
# executable code there is a syntax error. So:
#   1. if the script has a top-level param() block, insert after its closing paren;
#   2. otherwise insert after the first plain `$root = ...` assignment.
ROOT_DEF = re.compile(
    r"^[ \t]*\$root[ \t]*=[^\r\n]*$",
    re.MULTILINE | re.IGNORECASE,
)
PARAM_OPEN = re.compile(r"^[ \t]*param[ \t]*\(", re.MULTILINE | re.IGNORECASE)


def _param_block_end(text: str) -> int | None:
    """Index just past the closing ')' of the first top-level param() block."""
    m = PARAM_OPEN.search(text)
    if m is None:
        return None
    depth = 0
    i = m.end() - 1                     # at the '('
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _insertion_point(text: str) -> int:
    """Offset at statement level where the $hleRoot definition can safely go."""
    end = _param_block_end(text)
    if end is not None:
        return end
    m = ROOT_DEF.search(text)
    if m is None:
        raise SystemExit("  !! no param() block and no $root assignment; cannot insert")
    return m.end()


DEF_TEMPLATE = """
{indent}# The emulator lives in its own folder now (the tree mirrors the shipped
{indent}# ./Release layout). Fall back to the flat layout so these scripts keep working
{indent}# either way -- same rule GameManager.ps1 uses.
{indent}$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\\touchHLE.exe')) {{
{indent}    Join-Path $root 'touchHLE'
{indent}}} else {{
{indent}    $root
{indent}}}
"""


def transform(text: str) -> tuple[str, int]:
    hits = 0

    def _join(m: re.Match[str]) -> str:
        nonlocal hits
        hits += 1
        return f"Join-Path $hleRoot {m.group(2)}{m.group('rel')}"

    def _gci(m: re.Match[str]) -> str:
        nonlocal hits
        hits += 1
        return f"Get-ChildItem $hleRoot -Filter {m.group(2)}{m.group('rel')}"

    def _bare(m: re.Match[str]) -> str:
        nonlocal hits
        hits += 1
        return f"$hleRoot\\{m.group('rel')}"

    text = JOIN.sub(_join, text)
    text = GCI.sub(_gci, text)
    text = BARE.sub(_bare, text)

    if hits == 0:
        return text, 0

    insert_at = _insertion_point(text)
    text = text[:insert_at] + DEF_TEMPLATE.format(indent="") + text[insert_at:]
    return text, hits


def transform_py(text: str) -> tuple[str, int]:
    """Same idea for the handful of Python scripts that build emulator paths."""
    root_var = _py_root_var(text)
    if root_var is None:
        return text, 0

    hits = 0

    def _py(m: re.Match[str]) -> str:
        nonlocal hits
        hits += 1
        return f"_HLE / {m.group('q')}{m.group('rel')}{m.group('q')}"

    new = PY.sub(_py, text)
    if hits == 0:
        return text, 0

    # Put the constant right after the root assignment, so ROOT is already bound.
    m = re.search(rf"^{root_var}\s*=[^\n]*$", new, re.MULTILINE)
    assert m is not None
    body = PY_CONST.replace("ROOT", root_var)
    new = new[:m.end()] + "\n" + body + new[m.end():]
    return new, hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()

    # This script and its sibling are the reorganisation tooling itself.
    self_names = {Path(__file__).name, "_reorg_touchhle.py"}

    ps1: list[Path] = []
    ps1 += sorted(p for p in ROOT.glob("*.ps1"))
    ps1 += sorted(p for p in (ROOT / "_analysis").glob("*.ps1"))

    py: list[Path] = sorted(p for p in (ROOT / "_analysis").glob("*.py"))

    changed = skipped = 0

    def handle(path: Path, fn) -> None:
        nonlocal changed, skipped
        if path.name in self_names:
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"  skip (not utf-8) {path.name}")
            return

        if "$hleRoot =" in text or "_HLE =" in text:
            skipped += 1
            return

        new, hits = fn(text)
        if hits == 0:
            return

        rel = path.relative_to(ROOT)
        print(f"  {rel}  ({hits} reference(s))")
        if args.apply:
            path.write_text(new, encoding="utf-8")
        changed += 1

    for path in ps1:
        handle(path, transform)
    for path in py:
        handle(path, transform_py)

    print()
    print(f"{'rewritten' if args.apply else 'would rewrite'}: {changed}   already done: {skipped}")
    if not args.apply:
        print("(dry run -- pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

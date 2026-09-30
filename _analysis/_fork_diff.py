#!/usr/bin/env python3
"""Recover which source files the ZFR-adapted fork touched, by mining the
panic-message source locations that Rust embeds in both executables.

Rust's panic machinery embeds strings of the form

    src/some/file.rs:123:45

for every panicking site (assert!, unreachable!, unwrap(), index bounds, ...).
The fork and a freshly-built upstream trunk binary therefore contain two
different sets of these. Anything present in the fork but absent from trunk is
either a file the fork edited, or a code path upstream removed.

This is a cheap way to find the fork's compatibility patches without its source.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(ROOT)

# The emulator lives in its own folder now (the tree mirrors the shipped ./Release
# layout). Fall back to the flat layout so this keeps working either way.
_HLE = ROOT / "touchHLE"
if not (_HLE / "touchHLE.exe").exists():
    _HLE = ROOT

FORK = _HLE / "touchHLE.exe"
TRUNK = ROOT / "touchHLE_fixed.exe"

# src\...rs:LINE:COL  (Rust on Windows embeds backslashes)
LOC = re.compile(rb"(?:[A-Za-z]:\\[^\x00\"']{0,180}?\\|src\\)([A-Za-z0-9_\\/.-]+\.rs):(\d+):(\d+)")
STR = re.compile(rb"[\x20-\x7e]{6,}")


def scan(path):
    data = path.read_bytes()
    # file -> set of line numbers mentioned
    files = {}
    for m in LOC.finditer(data):
        name = m.group(1).decode("ascii", "replace").replace("\\", "/")
        line = int(m.group(2))
        files.setdefault(name, set()).add(line)
    strings = set()
    for m in STR.finditer(data):
        strings.add(m.group(0))
    return files, strings


def main():
    ff, fs = scan(FORK)
    tf, ts = scan(TRUNK)
    print(f"fork  {FORK.name}: {len(ff)} source files, {len(fs)} strings")
    print(f"trunk {TRUNK.name}: {len(tf)} source files, {len(ts)} strings")

    only_fork = sorted(set(ff) - set(tf))
    print(f"\n=== source files referenced ONLY by the fork ({len(only_fork)}) ===")
    for f in only_fork:
        lines = sorted(ff[f])
        print(f"  {f}   lines={lines[:12]}{'...' if len(lines) > 12 else ''}")

    only_trunk = sorted(set(tf) - set(ff))
    print(f"\n=== source files referenced ONLY by trunk ({len(only_trunk)}) ===")
    for f in only_trunk[:40]:
        print(f"  {f}")

    # For files present in BOTH, compare the referenced line numbers: a fork
    # edit usually shifts or adds panicking sites.
    print("\n=== files in both, with differing panic-site line sets ===")
    both = sorted(set(ff) & set(tf))
    diff_count = 0
    for f in both:
        if ff[f] != tf[f]:
            diff_count += 1
            a = sorted(ff[f])
            b = sorted(tf[f])
            print(f"  {f}")
            print(f"      fork : {a[:14]}")
            print(f"      trunk: {b[:14]}")
    print(f"  ({diff_count} differing of {len(both)} common files)")

    # Interesting strings unique to the fork (skip obvious build noise).
    print("\n=== fork-only strings mentioning ZFR/Zombie/touchHLE ===")
    n = 0
    for s in sorted(fs - ts):
        t = s.decode("ascii", "replace")
        if any(k in t for k in ("Zombie", "ZFR", "zfr", "touchHLE", "FastDirector",
                                "ApItems", "NSSearchPath", "Flurry")):
            print(f"  {t[:150]}")
            n += 1
            if n > 60:
                print("  ...")
                break


if __name__ == "__main__":
    main()

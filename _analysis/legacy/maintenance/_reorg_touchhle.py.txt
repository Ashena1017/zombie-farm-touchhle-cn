#!/usr/bin/env python3
r"""Reorganise the development tree so it mirrors the shipped ./Release layout.

Goal (the human's request): "touchHLE-related things go into ./touchHLE, everything
else outside it goes into the game-management side."

After this runs the root looks like the Release bundle's root, plus the development
directories that are NOT part of the shipped bundle (tools/, _analysis/, Release/):

    <root>\
    |-- TECHNICAL.md  process.md
    |-- GameManager.ps1  游戏管理.exe  launcher_selected_ipa.txt
    |-- StartZombieFarmNextHour.ps1  RestoreTestSave.ps1  SetZombieFarmCurrency.ps1
    |-- 运行游戏.bat  选择跳过时间并启动.bat  使用教程.txt
    |-- MSVCP140.dll  VCRUNTIME140.dll  VCRUNTIME140_1.dll
    |-- zombie_farm_ipa\      tools\      _analysis\      Release\
    `-- touchHLE\         <- everything emulator-related

The move is a same-volume rename, so it is instant even for the 4.8 GB toolchain.

This script is IDEMPOTENT: anything already in place is skipped, so a partial run
can simply be repeated. It records every move it makes to a log, so a rollback is a
matter of replaying that log backwards.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HLE = ROOT / "touchHLE"

# Everything here belongs to the emulator (or is one of its build inputs).
# Names are exactly as they appear in the root today.
DIRS = [
    "touchHLE_dylibs",       # runtime: the .dylib set touchHLE loads
    "touchHLE_fonts",        # runtime: fallback fonts
    "touchHLE_sandbox",      # runtime: per-app save containers
    "touchHLE-fork",         # source: upstream fa3d095 + the ZFR/60fps mods
    "touchHLE-trunk",        # source: upstream trunk, reference only
    "_build_tools",          # self-contained rust/cmake toolchain + cargo cache
]

FILES = [
    "touchHLE.exe",
    "touchHLE_fork.exe",
    # Local backups taken before each emulator swap. Kept (the human asked for them
    # to be preserved, just out of the way).
    "touchHLE.exe.backup-20260827-222546",
    "touchHLE.exe.backup-fps60-20260919-204040",
    "touchHLE.exe.backup-precrash-20260920-015739",
    # touchHLE's own per-app options and the default template.
    "touchHLE_default_options.txt",
    "touchHLE_options.txt",
    # Runtime state written by touchHLE / the launcher. All of these are resolved
    # through GameManager's $script:HleDir, so they follow the move automatically.
    "touchHLE_log.txt",
    "touchHLE_time_offset_seconds.txt",
    "zfr_last_launch.txt",
    "zfr_last_run.log",
    # A codex-extracted copy of the dylib the game ships inside the IPA. Unused by
    # the launcher, but it is emulator material.
    "zfrpatch_current.dylib",
    # Root LICENSE is touchHLE's MPL-2.0 text (17,100 B, identical to the copy the
    # Release builder writes as touchHLE/LICENSE-touchHLE.txt). It belongs with it.
    "LICENSE",
]

# Things that must NOT move: the game side and the development-only directories.
STAY = [
    "TECHNICAL.md", "process.md",
    "GameManager.ps1", "游戏管理.exe", "launcher_selected_ipa.txt",
    "StartZombieFarmNextHour.ps1", "RestoreTestSave.ps1", "SetZombieFarmCurrency.ps1",
    "运行游戏.bat", "选择跳过时间并启动.bat", "使用教程.txt",
    "MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll",
    "zombie_farm_ipa", "tools", "_analysis", "Release",
    # A local backup of the launcher script (game-management side, not emulator).
    "StartZombieFarmNextHour.ps1.backup-20260919-204040",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default=str(ROOT / "_analysis" / "dumps" / "_reorg_moves.json"))
    args = ap.parse_args()

    moves: list[tuple[str, str]] = []
    skipped: list[str] = []
    missing: list[str] = []

    if not args.dry_run:
        HLE.mkdir(exist_ok=True)

    for name in DIRS + FILES:
        src = ROOT / name
        dst = HLE / name
        if dst.exists():
            skipped.append(name)
            continue
        if not src.exists():
            missing.append(name)
            continue
        kind = "dir " if src.is_dir() else "file"
        size = ""
        if src.is_file():
            size = f"{src.stat().st_size:>12,} B"
        print(f"  move {kind} {name:<44} {size}")
        if not args.dry_run:
            shutil.move(str(src), str(dst))
        moves.append((name, str(src)))

    print()
    print(f"moved   : {len(moves)}")
    print(f"already : {len(skipped)} {skipped if skipped else ''}")
    if missing:
        print(f"MISSING : {len(missing)} {missing}")

    if not args.dry_run:
        Path(args.log).write_text(
            json.dumps({"root": str(ROOT), "moves": moves}, indent=2), encoding="utf-8")
        print(f"log     : {args.log}")

    # Anything left in the root that is neither expected-to-stay nor expected-to-move
    # is worth reporting: it means the inventory above is out of date.
    expected = set(DIRS) | set(FILES) | set(STAY) | {"touchHLE"}
    leftover = sorted(p.name for p in ROOT.iterdir() if p.name not in expected)
    if leftover:
        print(f"UNEXPECTED leftovers in root: {leftover}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

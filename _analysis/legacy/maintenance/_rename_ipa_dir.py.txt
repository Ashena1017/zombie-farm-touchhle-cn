# -*- coding: utf-8 -*-
"""Rename the IPA folder references: zombie_farm -> zombie_farm_ipa.

One-shot 2026-09-20 migration script. Byte-level replacement so UTF-8 BOMs
in .ps1 files survive untouched. Kept for provenance: the rename is DONE, so a
run today should report "files changed: 0". NOTE: this file is in its own
SKIP_FILES -- when it was first written it was NOT, and the run rewrote the
regex literals below (self-match). They were restored by hand; if you ever
re-enable the rename, re-check this file's literals first.

Scope:
  - root live files (GameManager.ps1, StartZombieFarmNextHour.ps1, 使用教程.txt)
    -- NOT TECHNICAL.md / process.md: those narrate the rename and must keep the
    old name as prose
  - Release live files (GameManager.ps1, 使用说明.txt)
  - tools\\**\\*.py
  - _analysis\\**\\*.{py,ps1,md}  MINUS archive/, reports/, dumps/, perf/,
    __pycache__/, save_backups_safe/ (historical or generated, keep as-is)

Protected tokens (NOT renamed, they are touchHLE source/debug artefacts):
  zombie_farm_ipa / zombie_farm.rs / zombie_farm_debug /
  zombie_farm_inspector / zombie_farm_crash_snapshot
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAT = re.compile(
    rb"zombie_farm(?!_ipa)(?!_crash_snapshot)(?!_debug)(?!_inspector)(?!\.rs)"
)
ANY = re.compile(rb"zombie_farm[\w\.]*")

EXCLUDE_DIRS = {
    "archive", "reports", "dumps", "perf", "__pycache__",
    "save_backups_safe", "touchHLE", ".git", "node_modules",
}
# _fetch_fork_src.ps1 greps touchHLE *source* for the module name
# 'zombie_farm' (src/objc/messages/zombie_farm.rs) -- renaming the pattern
# would break the search. TECHNICAL.md / process.md narrate the rename and must
# keep the old name as prose.
SKIP_FILES = {"_fetch_fork_src.ps1", "_rename_ipa_dir.py",
              "TECHNICAL.md", "process.md"}

ROOT_FILES = [
    "GameManager.ps1",
    "StartZombieFarmNextHour.ps1",
    "使用教程.txt",
]
RELEASE_FILES = [
    "GameManager.ps1",
    "使用说明.txt",
]

targets = []
for name in ROOT_FILES:
    p = ROOT / name
    if p.exists():
        targets.append(p)
    else:
        print("MISSING root file:", name)
rel = ROOT / "Release"
for name in RELEASE_FILES:
    p = rel / name
    if p.exists():
        targets.append(p)
    else:
        print("MISSING Release file:", name)

for base in ("tools", "_analysis"):
    for p in (ROOT / base).rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".py", ".ps1", ".md"):
            continue
        parts = set(p.relative_to(ROOT).parts[:-1])
        if parts & EXCLUDE_DIRS:
            continue
        if p.name in SKIP_FILES:
            print("SKIP (protected file):", p.relative_to(ROOT))
            continue
        targets.append(p)

changed = kept = 0
for p in sorted(set(targets)):
    data = p.read_bytes()
    occurrences = len(ANY.findall(data))
    if occurrences == 0:
        continue
    new, n = PAT.subn(b"zombie_farm_ipa", data)
    relname = str(p.relative_to(ROOT))
    if new != data:  # only real content changes count; identical-byte rewrites don't
        p.write_bytes(new)
        print("CHANGED {:>3} occ (renamed {:>2}): {}".format(occurrences, n, relname))
        changed += 1
    else:
        left = sorted(set(m.group().decode() for m in ANY.finditer(data)))
        print("KEPT   {:>3} occ, all already-new/protected: {} {}".format(occurrences, relname, left))
        kept += 1

print("---")
print("files changed:", changed, "| files kept:", kept)

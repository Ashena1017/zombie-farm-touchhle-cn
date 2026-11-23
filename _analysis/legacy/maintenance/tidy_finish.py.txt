"""HISTORICAL - do not run. Superseded by the 2026-09-23 cleanup.

This was the 2026-09-20 tidy-up: it moved stray root *.txt into dumps/,
old reports into reports/, and淘汰的 tools into archive/tools/.

Its file lists are now STALE and re-running it would be wrong:
  * the archived-file lists name things that have since been deleted
    (the _claude_* / history_* conversation extracts, the big hist_* dumps)
  * it ends by deleting every __pycache__, which is harmless but pointless
  * LIVE_TOOLS / LIVE_ZT no longer match tools/ (which now keeps 46 modules)

Kept only as a record of how the archive was laid out. See _analysis/README.md.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "_analysis"
DIRS = {
    "archive": AN / "archive",
    "archive_tools": AN / "archive" / "tools",
    "dumps": AN / "dumps",
    "reports": AN / "reports",
}
KEEP_TXT = {
    "touchHLE_default_options.txt", "touchHLE_options.txt",
    "touchHLE_time_offset_seconds.txt", "touchHLE_log.txt",
    "zfr_last_launch.txt", "使用教程.txt",
}
REPORT_TXT = {"_claude_assistant.txt", "_claude_human_msgs.txt",
              "history_user_text.txt", "history_agent_messages.txt",
              "history_agent_text.txt"}
REPORT_MD = {"ZFR_v4_v5_报告.md", "ZFR_v6_与三个新问题.md", "ZFR_图3_任务计数_深挖报告.md"}
SKIP = {"tidy_finish.py", "_reorg.py", "_reorg.out.txt"}

LIVE_TOOLS = set("""
    audit_zfr_ipa inspect_v3_facts patch_zfr_alert_fonts value_xref dump_window
    ivar_xref annot_disasm dump_ivars
    patch_zfr_fonts_v3 patch_zfr_helper_v4 v4_verify
    patch_zfr_fonts_v5 v5_validate v5_verify
    patch_zfr_fonts_v6 v6_verify
    patch_zfr_questdiag_v7 patch_zfr_questdiag_v8 patch_zfr_questdiag_v9
    patch_zfr_questfix_v10 patch_zfr_questfix_v11
    patch_zfr_ability_v13 patch_zfr_lang_v14
    v4_cave_map v4_sites v5_sites unlock_font_sites audit_alert_fonts_all
""".split())
LIVE_ZT = {"zscan", "c13_final", "c14_v3diff", "ann"}

moved = failed = 0


def move(src: Path, dst_dir: Path):
    global moved, failed
    if not src.exists() or src.name in SKIP:
        return
    dst = dst_dir / src.name
    if dst.exists():
        print("  skip (already there): %s" % src.name)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dst))
        moved += 1
        print("  %-58s -> %s" % (src.relative_to(ROOT), dst.relative_to(ROOT)))
    except (PermissionError, OSError) as exc:
        failed += 1
        print("  LOCKED %s (%s)" % (src.name, exc.strerror or exc))


for d in DIRS.values():
    d.mkdir(parents=True, exist_ok=True)

print("-- root text dumps")
for p in sorted(ROOT.glob("*.txt")):
    if p.name in KEEP_TXT:
        continue
    move(p, DIRS["reports"] if p.name in REPORT_TXT else DIRS["dumps"])

print("-- historic reports")
for name in sorted(REPORT_MD):
    move(ROOT / name, DIRS["reports"])

print("-- stray artefacts")
move(ROOT / "_v4_dryrun.json", DIRS["dumps"])

print("-- tools/")
for p in sorted((ROOT / "tools").glob("*.py")):
    if p.stem not in LIVE_TOOLS:
        move(p, DIRS["archive_tools"])
for p in sorted((ROOT / "tools").glob("*.txt")):
    move(p, DIRS["dumps"])
zt = ROOT / "tools" / "_zt"
if zt.is_dir():
    for p in sorted(zt.glob("*.py")):
        if p.stem not in LIVE_ZT:
            move(p, DIRS["archive_tools"] / "_zt")

print("-- old ad-hoc folders")
for name in ("_advver", "_adv_verify", "_scratch", "_vp"):
    src = ROOT / name
    if src.exists():
        dst = DIRS["archive"] / name
        if dst.exists():
            print("  skip (already there): %s" % name)
            continue
        try:
            shutil.move(str(src), str(dst))
            moved += 1
            print("  %-58s -> %s" % (name, dst.relative_to(ROOT)))
        except OSError as exc:
            failed += 1
            print("  LOCKED %s (%s)" % (name, exc))

print("-- bytecode caches")
for pc in list(ROOT.rglob("__pycache__")):
    shutil.rmtree(pc, ignore_errors=True)
    print("  removed %s" % pc.relative_to(ROOT))

print("\nmoved %d, locked/failed %d" % (moved, failed))
sys.exit(1 if failed else 0)

"""Compute the live subset of tools/ : transitive closure of local imports from
the documented seed modules, plus anything the root analysis scripts import."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"

SEED = [
    "audit_zfr_ipa", "inspect_v3_facts", "patch_zfr_alert_fonts",
    "value_xref", "dump_window", "ivar_xref",
    "patch_zfr_fonts_v3", "patch_zfr_helper_v4", "v4_verify",
    "patch_zfr_fonts_v5", "v5_validate", "v5_verify",
    "patch_zfr_fonts_v6", "v6_verify",
    "patch_zfr_questdiag_v7", "patch_zfr_questdiag_v8", "patch_zfr_questdiag_v9",
    "patch_zfr_questfix_v10", "patch_zfr_questfix_v11",
    "patch_zfr_ability_v13", "patch_zfr_lang_v14",
    "v4_cave_map", "v4_sites", "v5_sites", "unlock_font_sites",
    "audit_alert_fonts_all",
]

local = {p.stem: p for p in TOOLS.rglob("*.py")}
local.update({p.stem: p for p in (ROOT / "_zt").rglob("*.py")} if (ROOT / "_zt").exists() else {})

# hard-coded seeds that also live in the *root* analysis scripts
def imports_of(path: Path):
    src = path.read_text(encoding="utf-8", errors="replace")
    out = set()
    for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", src, re.M):
        name = m.group(1).split(".")[0]
        if name in local:
            out.add(name)
    return out


live = set()
stack = list(SEED)
# root analysis scripts too
for p in list(ROOT.glob("_*.py")) + list(ROOT.glob("_verify_*.py")):
    src = p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", src, re.M):
        n = m.group(1).split(".")[0]
        if n in local:
            stack.append(n)

while stack:
    n = stack.pop()
    if n in live or n not in local:
        continue
    live.add(n)
    stack.extend(imports_of(local[n]))

print("live tools modules (%d):" % len(live))
for n in sorted(live):
    print("   %-32s %s" % (n, local[n].relative_to(ROOT)))
print()
dead = sorted(set(local) - live)
print("everything else in tools/ (%d):" % len(dead))
for n in dead:
    print("   %-32s %s" % (n, local[n].relative_to(ROOT)))

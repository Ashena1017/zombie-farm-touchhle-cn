
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
import sys, zipfile, plistlib
IPA=str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
with zipfile.ZipFile(IPA) as z:
    q=plistlib.loads(z.read("Payload/ZFR.app/Quests.plist"))
    e=plistlib.loads(z.read("Payload/ZFR.app/Enemies.plist"))
print("Enemies.plist type:", type(e).__name__)
if isinstance(e,dict): items=e.items()
elif isinstance(e,list): items=[(i,d) for i,d in enumerate(e)]
names=set()
for k,v in items:
    if isinstance(v,dict):
        nm=v.get("name")
        if nm: names.add(nm)
        print("  enemy[%s] name=%r  keys=%s" % (k, nm, sorted(v.keys())[:12]))
    else:
        print("  enemy[%s] = %r" % (k, v))
print("\n=== Quests.plist 中 kInvasionSuccessfulNotification 的 notificationObject ===")
qs=set()
for i,d in enumerate(q):
    for r in (d.get("requirements") or []):
        if r.get("notificationID")=="kInvasionSuccessfulNotification":
            no=r.get("notificationObject")
            qs.add(no)
            match = "MATCH" if no in names else "*** NO MATCH ***"
            print("  quest[%2d] %-28r  %s" % (i, no, match))
print("\n=== 差集 ===")
print("  仅任务有:", sorted(x for x in qs if x not in names))
print("  仅敌人有:", sorted(x for x in names if x not in qs))

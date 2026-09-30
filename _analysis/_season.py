import zipfile, plistlib, io, os, sys, json

IPA = r"zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa"

z = zipfile.ZipFile(IPA)
names = [n for n in z.namelist() if n.lower().endswith("quests.plist")]
print("candidates:", names)
p = names[0]
data = z.read(p)
try:
    pl = plistlib.loads(data)
except Exception:
    pl = plistlib.loads(data, fmt=plistlib.FMT_BINARY)

print("type:", type(pl))
if isinstance(pl, dict):
    print("keys:", list(pl.keys())[:20])
    arr = None
    for k, v in pl.items():
        if isinstance(v, list):
            arr = v
            print("list key:", k, "len", len(v))
    if arr is None:
        arr = [pl]
else:
    arr = pl

print("entries:", len(arr))
print("entry 0 keys:", sorted(arr[0].keys()))

def show(i, q):
    print("---- [%d]" % i)
    for k in sorted(q.keys()):
        v = q[k]
        s = repr(v)
        if len(s) > 300:
            s = s[:300] + " ..."
        print("   %-20s %s" % (k, s))

for i, q in enumerate(arr):
    blob = repr(q)
    if "Seasonal" in blob:
        show(i, q)

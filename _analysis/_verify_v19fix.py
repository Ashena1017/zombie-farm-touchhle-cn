#!/usr/bin/env python3
"""Independent verifier for v19fix (does not import the patcher)."""
import hashlib
import plistlib
import sys
import zipfile
from pathlib import Path

ROOT = next(p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
            if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(ROOT / "tools"))
from audit_zfr_ipa import parse_fat  # noqa: E402
from patch_zfr_alert_fonts import fat_descriptors, parse_zip_layout  # noqa: E402

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
Z = ROOT / "zombie_farm_ipa"
OLD = Z / f"{BASE}.fixed-fonts-v18fix.ipa"
NEW = Z / f"{BASE}.fixed-fonts-v19fix.ipa"
BASEIPA = Z / "ZFR 1.0.zh-CN-unsigned.ipa"
EXE = "Payload/ZFR.app/ZFR"
MEMBERS = ["Payload/ZFR.app/Arial-BoldMT.strings",
           "Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings"]
FAIL = []

V18_SHA = "D84A536BC2351A633E739F7BBED0A0C4FD586688E506B8A578A037536CB55CE4"
V19_SHA = "760D183FCE12081D8BFC87C6DBAC5762ADC26C9EAC6C483A7D643D116296E206"


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


old_raw, new_raw = OLD.read_bytes(), NEW.read_bytes()

print("== 1. archive ==")
check(len(old_raw) == len(new_raw) == 59564493, "both are 59,564,493 bytes")
check(hashlib.sha256(old_raw).hexdigest().upper() == V18_SHA, "input really is v18fix")
check(hashlib.sha256(new_raw).hexdigest().upper() == V19_SHA, "output sha256 as reported")
with zipfile.ZipFile(NEW) as z:
    check(z.testzip() is None, "v19fix passes testzip()")
    new_exe = z.read(EXE)
    new_members = {n: z.read(n) for n in MEMBERS}
    truth = plistlib.loads(z.read("Payload/ZFR.app/zh-Hans.lproj/Localizable.strings"))
with zipfile.ZipFile(OLD) as z:
    old_exe = z.read(EXE)

print("\n== 2. the executable is untouched ==")
check(new_exe == old_exe, "the ZFR executable is byte-identical to v18fix")
check(fat_descriptors(new_exe) == fat_descriptors(old_exe), "FAT descriptors unchanged")

print("\n== 3. only the two Arial-BoldMT members changed ==")
with zipfile.ZipFile(OLD) as z:
    old_names = {i.filename: (i.file_size, i.compress_size) for i in z.infolist()}
with zipfile.ZipFile(NEW) as z:
    new_names = {i.filename: (i.file_size, i.compress_size) for i in z.infolist()}
check(set(old_names) == set(new_names), "same member set")
diff = [n for n in old_names if old_names[n] != new_names[n]]
check(sorted(diff) == sorted(MEMBERS), "exactly the two members changed: %s" % diff)
check(all(old_names[n][1] == new_names[n][1] for n in old_names),
      "every member keeps its compressed slot size (no offset moved)")
check(len({parse_zip_layout(new_raw)["records"][i]["local_offset"]
           for i in range(len(parse_zip_layout(new_raw)["records"]))}) ==
      len(parse_zip_layout(new_raw)["records"]), "local offsets are still distinct")

print("\n== 4. the repaired table holds the right Chinese ==")
WANT = {"Fertilized by %@!": "%@施肥",
        "Cupid Zombie": "丘比特僵尸",
        "Flower Zombie": "花花僵尸",
        "Garden Zombie": "园丁僵尸",
        "Green Flower Zombie": "花花僵尸",
        "ZomBotanist": "生态僵尸",
        "Zombee": "蜜蜂僵尸",
        "Zombutterfly": "蝴蝶僵尸"}
for name in MEMBERS:
    table = plistlib.loads(new_members[name])
    check(set(table) == set(WANT), "%s keeps all 8 keys" % name)
    for k, v in WANT.items():
        check(table.get(k) == v, "   %-22r -> %r" % (k, table.get(k)))
    check(len(new_members[name]) <= 257, "%s shrank (253 <= 257)" % name)

print("\n== 5. every value matches Localizable.strings (except the shortened one) ==")
for name in MEMBERS:
    table = plistlib.loads(new_members[name])
    for k, v in table.items():
        if k == "Fertilized by %@!":
            check(v == "%@施肥" and truth[k] == " %@施肥了",
                  "   %r shortened from %r to fit the slot" % (k, truth[k]))
        else:
            check(v == truth[k], "   %r == Localizable.strings" % k)

print("\n== 6. no mojibake left in the members ==")
for name in MEMBERS:
    raw = new_members[name]
    blob = plistlib.loads(raw)
    bad = [k for k, v in blob.items() if any(0x00A0 <= ord(c) <= 0x024F for c in v)]
    check(not bad, "%s: no Latin-1/Latin-Extended characters left (%s)" % (name, bad))

print("\n== 7. the baseline never had this table, so nothing regressed ==")
with zipfile.ZipFile(BASEIPA) as z:
    base_names = set(z.namelist())
for name in MEMBERS:
    check(name not in base_names,
          "%s is a codex addition (absent from the untouched baseline)" % name)

print("\n== 8. earlier fixes survive (through the untouched executable) ==")
sl = {s.subtype: s for s in parse_fat(new_exe)}
o = sl[9].addr_to_file(0x54272)
check(new_exe[o:o + 4] == old_exe[o:o + 4], "v17 voucher retarget intact")
o = sl[9].addr_to_file(0x1138A0)
check(new_exe[o:o + 26] == old_exe[o:o + 26], "v17 stub intact")
check(plistlib.loads(new_members[MEMBERS[1]]).get("Zombee") == "蜜蜂僵尸",
      "the fertilize/jungle-zombie names render in Chinese")

print()
if FAIL:
    print("VERIFICATION FAILED (%d)" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")

"""Build ...fixed-fonts-v29fix-notice.ipa: v29fix with one texture replaced.

Every other member is written back with its original content, order, compression
method and timestamp, and is verified byte-identical afterwards.  The Mach-O
executable hash is unchanged, so the notice layer is the only difference.

Run _make_notice_texture.py first.
"""
import datetime
import hashlib
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IPADIR = os.path.join(ROOT, "zombie_farm_ipa")

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
OUT = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa"
MEMBER = "Payload/ZFR.app/MainMenuBG.png"
EXE = "Payload/ZFR.app/ZFR"
TEXTURE = os.path.join(HERE, "dumps", "release-assets", "MainMenuBG.notice.png")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest().upper()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    src = os.path.join(IPADIR, BASE)
    dst = os.path.join(IPADIR, OUT)
    with open(TEXTURE, "rb") as f:
        png = f.read()
    print("texture", len(png), sha256_bytes(png))

    if os.path.exists(dst):
        os.remove(dst)

    before = {}
    replaced = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            before[info.filename] = hashlib.sha256(data).hexdigest()
            if info.filename == MEMBER:
                data = png
                replaced += 1
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.internal_attr = info.internal_attr
            zi.create_system = info.create_system
            zout.writestr(zi, data)

    if replaced != 1:
        raise SystemExit("replaced %d members, expected 1" % replaced)

    # --- verify -------------------------------------------------------------
    with zipfile.ZipFile(dst) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit("corrupt member: %s" % bad)
        names = [i.filename for i in z.infolist()]
        if names != list(before):
            raise SystemExit("member list/order changed")
        diffs = []
        for n in names:
            got = hashlib.sha256(z.read(n)).hexdigest()
            if got != before[n]:
                diffs.append(n)
        if diffs != [MEMBER]:
            raise SystemExit("unexpected content changes: %r" % diffs)
        if sha256_bytes(z.read(MEMBER)) != sha256_bytes(png):
            raise SystemExit("texture did not round-trip")

    exe_in = None
    with zipfile.ZipFile(src) as z:
        exe_in = sha256_bytes(z.read(EXE))
    with zipfile.ZipFile(dst) as z:
        exe_out = sha256_bytes(z.read(EXE))

    src_sha = sha256_file(src)
    dst_sha = sha256_file(dst)
    rep = {
        "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": "_build_notice_ipa.py",
        "kind": "NOTICE",
        "supersedes": BASE,
        "purpose": (
            "Burn the free/open-source notice into the main-menu background so every "
            "launch shows it. Resale copies of this build advertise the original."
        ),
        "members": [
            {
                "member": MEMBER,
                "change": "sky layer repainted: right-top notice block",
                "size_before": 319107,
                "size_after": len(png),
                "sha256_after": sha256_bytes(png),
            }
        ],
        "member_count": len(before),
        "other_members_unchanged": len(before) - 1,
        "input": {"name": BASE, "size": os.path.getsize(src), "sha256": src_sha},
        "output": {
            "name": OUT,
            "size": os.path.getsize(dst),
            "sha256": dst_sha,
            "executable_sha256": exe_out,
        },
    }
    if exe_in != exe_out:
        raise SystemExit("executable changed!")

    rp = os.path.join(IPADIR, OUT.replace(".ipa", ".report.json"))
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("wrote", rp)
    print("size", os.path.getsize(dst), "sha256", dst_sha)
    print("exe", exe_out, "(unchanged)")


if __name__ == "__main__":
    main()

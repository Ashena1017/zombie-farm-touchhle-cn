"""Build ...fixed-fonts-v29fix-notice.ipa: v29fix with one texture replaced.

Every other member is written back with its original content, order, compression
method and timestamp, and is verified byte-identical afterwards.  The Mach-O
executable hash is unchanged, so the notice layer is the only difference.

Run _make_notice_texture.py first. For a different notice, pass both
--texture <png> and --output <new.ipa>.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IPADIR = ROOT / "zombie_farm_ipa"

BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
OUT = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa"
BASE_SHA256 = "E5951F945D23E88F25D0D1E7DC84E39AB524C566E28460173600BA05423C9DED"
OUT_SHA256 = "7BB214498B149E11DECA49C19E5A21B9AA7F763646537206B85CBBAB86582FFC"
MEMBER = "Payload/ZFR.app/MainMenuBG.png"
EXE = "Payload/ZFR.app/ZFR"
TEXTURE = ROOT / "_analysis" / "dumps" / "release-assets" / "MainMenuBG.notice.png"


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest().upper()


def sha256_stream(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest().upper()


def sha256_file(p):
    with open(p, "rb") as stream:
        return sha256_stream(stream)


def check_existing_ipa(path, report):
    if sha256_file(path) != report["output"]["sha256"]:
        raise ValueError(f"existing IPA differs: {path}; choose another --output")


def check_existing_report(path, report):
    with path.open(encoding="utf-8-sig") as stream:
        existing = json.load(stream)
    # An identical build keeps the original report, including its timestamp.
    if (not isinstance(existing, dict) or not isinstance(existing.get("generated"), str)
            or existing != {**report, "generated": existing["generated"]}):
        raise ValueError(f"existing report differs: {path}; choose another --output")


def install_missing(candidate, path, check_existing, report):
    try:
        if os.name == "nt":
            candidate.rename(path)
        else:
            os.link(candidate, path)
    except FileExistsError:
        check_existing(path, report)


def build(src, texture, dst):
    report_path = dst.with_suffix(".report.json")
    if dst.suffix.lower() != ".ipa" or {src.resolve(), texture.resolve()} & {
        dst.resolve(), report_path.resolve()
    }:
        raise ValueError("--output must be a separate .ipa file")
    png = texture.read_bytes()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("expected a PNG notice texture")

    with tempfile.TemporaryDirectory(prefix=".notice-build-", dir=dst.parent) as stage:
        candidate = Path(stage) / dst.name
        candidate_report = Path(stage) / report_path.name
        with src.open("rb") as source:
            if sha256_stream(source) != BASE_SHA256:
                raise ValueError("expected the original v29fix IPA as input")
            source.seek(0)
            report = build_candidate(source, candidate, png)
        if dst.name.casefold() == OUT.casefold() and report["output"]["sha256"] != OUT_SHA256:
            raise ValueError("build differs from the historical v29fix-notice IPA; choose another --output")
        with open(candidate_report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        # Check both before publishing either. Publish the verified IPA first
        # so an interrupted run can fill in its missing report on the next run.
        files = ((candidate, dst, check_existing_ipa),
                 (candidate_report, report_path, check_existing_report))
        missing = []
        for staged, path, check_existing in files:
            if path.exists():
                check_existing(path, report)
            else:
                missing.append((staged, path, check_existing))
        for staged, path, check_existing in missing:
            install_missing(staged, path, check_existing, report)
    return report


def build_candidate(src, dst, png):
    before = {}
    replaced = 0
    original_texture_size = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            before[info.filename] = hashlib.sha256(data).hexdigest()
            if info.filename == MEMBER:
                original_texture_size = len(data)
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

    dst_sha = sha256_file(dst)
    return {
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
                "size_before": original_texture_size,
                "size_after": len(png),
                "sha256_after": sha256_bytes(png),
            }
        ],
        "member_count": len(before),
        "other_members_unchanged": len(before) - 1,
        "input": {"name": BASE, "size": os.fstat(src.fileno()).st_size, "sha256": BASE_SHA256},
        "output": {
            "name": dst.name,
            "size": os.path.getsize(dst),
            "sha256": dst_sha,
            "executable_sha256": before[EXE].upper(),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=IPADIR / BASE)
    parser.add_argument("--texture", type=Path, default=TEXTURE)
    parser.add_argument("--output", type=Path, default=IPADIR / OUT)
    args = parser.parse_args()
    try:
        report = build(args.input, args.texture, args.output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"{args.output}  {report['output']['size']:,} bytes  SHA-256 {report['output']['sha256']}")
    print(f"report: {args.output.with_suffix('.report.json')}")


if __name__ == "__main__":
    main()

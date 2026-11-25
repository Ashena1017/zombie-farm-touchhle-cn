"""Build the v30 notice IPA from the verified v29 notice IPA (Python 3, Pillow)."""

import argparse
from copy import copy
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile

from PIL import Image

from _build_notice_ipa import sha256_file
from audit_zfr_ipa import parse_fat
from patch_zfr_alert_fonts import EXECUTABLE, fat_descriptors, sha256


IPA_DIR = Path(__file__).resolve().parents[1] / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-"
SOURCE = IPA_DIR / (BASE + "v29fix-notice.ipa")
TARGET = IPA_DIR / (BASE + "v30fix-notice.ipa")
SOURCE_SHA256 = "7BB214498B149E11DECA49C19E5A21B9AA7F763646537206B85CBBAB86582FFC"
TARGET_SHA256 = "9C7A4CBAFE0B7636B541F9D8F7D40BC7F0DCDD33C3440BEBA3FC3C731B718339"
FONTS = ("ABD26", "ATWBD26", "ATWBO26")

# The sell dialog's wrapper passes the same body label and localized string
# twice. Its next call reloads both arguments. Keep the first call and replace
# only the second BL with an ARMv6 MOV r0,r0 or two 16-bit Thumb NOPs.
SECOND_BODY_CALL = {
    6: (0x1B500, bytes.fromhex("620000eb"), bytes.fromhex("0000a0e1")),
    9: (0x14FE4, bytes.fromhex("00f096f8"), bytes.fromhex("00bf00bf")),
}


def patch_dialog(executable):
    offsets = {s["subtype"]: s["offset"] for s in fat_descriptors(executable)}
    result = bytearray(executable)
    for arch in parse_fat(executable):
        address, old, new = SECOND_BODY_CALL[arch.subtype]
        offset = arch.addr_to_file(address)
        if offset is None or arch.data[offset:offset + len(old)] != old:
            raise ValueError(f"unexpected instruction at {address:#x} in ARM subtype {arch.subtype}")
        start = offsets[arch.subtype] + offset
        result[start:start + len(old)] = new
    return bytes(result)


def crop_font(archive, name):
    stem = "Payload/ZFR.app/" + name
    description = archive.read(stem + ".fnt")
    if description.count(b"scaleW=2048 scaleH=2048") != 1:
        raise ValueError(f"{name}: unexpected BMFont scale")
    with Image.open(BytesIO(archive.read(stem + ".png"))) as image:
        if image.mode != "RGBA" or image.size != (2048, 2048):
            raise ValueError(f"{name}: unexpected atlas format")
        if any(channel != (0, 0) for channel in image.crop((0, 64, 2048, 2048)).getextrema()):
            raise ValueError(f"{name}: discarded rows contain nonzero pixel channels")
        cropped = image.crop((0, 0, 2048, 64))

    stream = BytesIO()
    cropped.save(stream, format="PNG")
    with Image.open(BytesIO(stream.getvalue())) as readback:
        if readback.mode != cropped.mode or readback.tobytes() != cropped.tobytes():
            raise ValueError(f"{name}: pixels changed in the PNG round trip")
    count = 0
    for line in description.splitlines():
        if line.startswith(b"char "):
            glyph = dict(token.split(b"=", 1) for token in line.split()[1:])
            x, y, w, h = (int(glyph[k]) for k in (b"x", b"y", b"width", b"height"))
            if min(x, y, w, h) < 0 or x + w > cropped.width or y + h > cropped.height:
                raise ValueError(f"{name}: glyph {glyph[b'id']} exceeds cropped bounds")
            count += 1
    if count != 122:
        raise ValueError(f"{name}: expected 122 glyphs, found {count}")
    return {
        stem + ".png": stream.getvalue(),
        stem + ".fnt": description.replace(b"scaleW=2048 scaleH=2048", b"scaleW=2048 scaleH=64"),
    }


def build(source, output):
    report_path = output.with_suffix(".report.json")
    if source.resolve() in (output.resolve(), report_path.resolve()) or output == report_path:
        raise ValueError("input, output and report must have separate paths")
    if sha256_file(source) != SOURCE_SHA256:
        raise ValueError("expected the official v29fix-notice IPA")
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        candidate = Path(temp) / "candidate.ipa"
        with ZipFile(source) as original:
            replacements = {EXECUTABLE: patch_dialog(original.read(EXECUTABLE))}
            for font in FONTS:
                replacements.update(crop_font(original, font))
            with ZipFile(candidate, "w") as archive:
                archive.comment = original.comment
                for member in original.infolist():
                    name = member.filename
                    data = replacements[name] if name in replacements else original.read(member)
                    archive.writestr(copy(member), data)
            with ZipFile(candidate) as archive:
                if archive.namelist() != original.namelist():
                    raise ValueError("ZIP member list or order changed")
                for name in archive.namelist():
                    expected = replacements[name] if name in replacements else original.read(name)
                    if archive.read(name) != expected:
                        raise ValueError(f"ZIP verification failed for {name}")
        report = {
            "tool": Path(__file__).name,
            "input": {"name": SOURCE.name, "sha256": SOURCE_SHA256},
            "output": {"name": TARGET.name, "size": candidate.stat().st_size, "sha256": sha256_file(candidate)},
            "members": {k: sha256(v) for k, v in sorted(replacements.items())},
            "font_atlas_dimensions": {"before": [2048, 2048], "after": [2048, 64], "glyphs_per_atlas": 122},
            "removed_duplicate_body_call": {f"sub{k}": hex(v[0]) for k, v in SECOND_BODY_CALL.items()},
        }
        if report["output"]["sha256"] != TARGET_SHA256:
            raise ValueError("encoded IPA differs from v30 (check Pillow and zlib versions)")
        staged_report = Path(temp) / "report.json"
        staged_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        try:
            if os.name == "nt":
                candidate.rename(output)
            else:
                os.link(candidate, output)
        except FileExistsError:
            if sha256_file(output) != TARGET_SHA256:
                raise ValueError(f"existing {output} differs from the verified build") from None
        staged_report.replace(report_path)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=TARGET)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output)["output"], indent=2))

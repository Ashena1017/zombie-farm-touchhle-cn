"""Add the landscape launch notice to the v30 IPA (Python 3.14+, Pillow)."""

import argparse
from copy import copy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont

from cumulative_ipa import IPA_DIR, publish


STEM = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-"
SOURCE = IPA_DIR / (STEM + "v30fix-notice.ipa")
TARGET = IPA_DIR / "内置中文版·v31fix·开源免费.ipa"
SOURCE_SHA256 = "9c7a4cbafe0b7636b541f9d8f7d40bc7f0dcdd33c3440beba3fc3c731b718339"
TARGET_SHA256 = "cfa750f4cba8d5acf0923c595ca3c257b0617c2cafed7d4ee08f4bc37d689e65"
MEMBER = "Payload/ZFR.app/Default.png"
NOTICE = "本整合版免费 · 请勿购买"


def launch_png(data, font_path):
    with Image.open(BytesIO(data)) as original:
        if original.mode != "RGBA" or original.size != (320, 480) or original.getextrema() != (
            (0, 0), (0, 0), (0, 0), (255, 255)
        ):
            raise ValueError("unexpected v30 launch image")
        landscape = original.transpose(Image.Transpose.ROTATE_270)
    font = ImageFont.truetype(str(font_path), size=16)
    ImageDraw.Draw(landscape).text(
        (landscape.width // 2, landscape.height - 25), NOTICE,
        anchor="mb", fill=(174, 174, 174, 255), font=font,
    )
    # touchHLE rotates the portrait launch texture clockwise for --landscape-right.
    png = BytesIO()
    landscape.transpose(Image.Transpose.ROTATE_90).save(png, format="PNG")
    return png.getvalue()


def build(source, font_path):
    data = source.read_bytes()
    if sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("expected the v30fix-notice IPA")
    result = BytesIO()
    with ZipFile(BytesIO(data)) as original, ZipFile(result, "w") as output:
        old_png = original.read(MEMBER)
        new_png = launch_png(old_png, font_path)
        output.comment = original.comment
        for item in original.infolist():
            output.writestr(copy(item), new_png if item.filename == MEMBER else original.read(item))
        member_count = len(original.infolist())
    ipa = result.getvalue()
    if sha256(ipa).hexdigest() != TARGET_SHA256:
        raise ValueError("build differs from v31 (check font, Pillow and zlib versions)")
    report = {
        "tool": Path(__file__).name,
        "input": {"name": SOURCE.name, "size": len(data), "sha256": SOURCE_SHA256},
        "output": {"name": TARGET.name, "size": len(ipa), "sha256": TARGET_SHA256},
        "launch_notice": NOTICE,
        "members": {
            MEMBER: {"before": sha256(old_png).hexdigest(), "after": sha256(new_png).hexdigest()}
        },
        "other_members_unchanged": member_count - 1,
    }
    return ipa, report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=TARGET)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msyh.ttc"))
    args = parser.parse_args()
    if args.output.suffix.lower() != ".ipa":
        parser.error("--output must be an .ipa filename")
    ipa, report = build(args.input, args.font)
    publish(args.output, ipa)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    publish(args.output.with_suffix(".report.json"), encoded.encode("utf-8"))
    print(json.dumps(report["output"]))

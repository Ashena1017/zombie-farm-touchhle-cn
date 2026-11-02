"""Generate the free/open-source notice texture burned into the title screen.

Only Payload/ZFR.app/MainMenuBG.png is touched: it is the sky + far-hills layer
of the main menu (1024x683, plain RGBA PNG).  The block goes in the empty sky to
the right of the logo, where nothing else is ever drawn on top of it.

Reads the layer straight out of the v29fix IPA so the run is reproducible.
Output: _analysis/dumps/release-assets/MainMenuBG.notice.png
"""
import io
import os
import zipfile
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE_IPA = os.path.join(ROOT, "zombie_farm_ipa",
                        "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa")
MEMBER = "Payload/ZFR.app/MainMenuBG.png"
OUT_DIR = os.path.join(HERE, "dumps", "release-assets")
OUT = os.path.join(OUT_DIR, "MainMenuBG.notice.png")

BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
REG = r"C:\Windows\Fonts\msyh.ttc"

LINE1 = "本作免费开源 · 请勿购买"
LINE2 = "github.com/Ashena1017/zombie-farm-touchhle-cn"

TITLE_PX = 26
URL_PX = 14
GAP = 5
MARGIN = (16, 26)


def load_source():
    with zipfile.ZipFile(BASE_IPA) as z:
        return Image.open(io.BytesIO(z.read(MEMBER))).convert("RGBA")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    base = load_source()
    W, H = base.size
    print("source", base.size, base.mode)

    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    f1 = ImageFont.truetype(BOLD, TITLE_PX)
    f2 = ImageFont.truetype(REG, URL_PX)
    w1 = d.textlength(LINE1, font=f1)
    w2 = d.textlength(LINE2, font=f2)
    block = max(w1, w2)
    x = W - MARGIN[0] - block
    y = MARGIN[1]
    d.text((x + block - w1, y), LINE1, font=f1, fill=(255, 255, 255, 240),
           stroke_width=3, stroke_fill=(28, 48, 78, 150))
    d.text((x + block - w2, y + TITLE_PX + GAP), LINE2, font=f2, fill=(255, 255, 255, 215),
           stroke_width=2, stroke_fill=(28, 48, 78, 130))

    out = Image.alpha_composite(base, lay)
    out.save(OUT, optimize=True)
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()

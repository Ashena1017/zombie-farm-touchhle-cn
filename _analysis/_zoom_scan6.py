# -*- coding: utf-8 -*-
"""Dump ZFFarmTileMap / ZFTileManager methods, and find who calls the zoom selectors."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat  # noqa: E402
from annot_disasm import annotate, method_index  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs  # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
EXECUTABLE = "Payload/ZFR.app/ZFR"

with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)

sl = [s for s in parse_fat(fat) if s.subtype == 9][0]

for CLS in ("ZFFarmTileMap", "ZFTileManager"):
    ms = [m for m in sl.methods if m.cls == CLS]
    print(f"\n================ {CLS} ({len(ms)} methods) ================")
    for m in sorted(ms, key=lambda x: x.selector):
        print(f"   {m.selector:60s} imp=0x{m.imp:x}")

# ---- find call sites of zoom selectors ----
TARGETS = ["setZoomOutAmount:", "resetCameraWithZoom:", "resetCamera", "scaleCompensation:",
           "zoomFactor"]
idx = method_index(sl)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
md.skipdata = True
txt = next(s for s in sl.sections if s.name == "__text")

for t in TARGETS:
    print(f"\n================ call sites of {t} ================")
    regs = {}
    hits = 0
    for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
        if not ins.id:
            regs.clear()
            continue
        note = annotate(sl, ins, True, idx, regs)
        if t in note:
            hits += 1
            at = ins.address & ~1
            prev = max((x for x in idx if x <= at), default=None)
            owner = ""
            if prev is not None and at - prev < 0x3000:
                n, s, k = idx[prev]
                owner = f"{n} {s} +{at - prev:#x}"
            print(f"   {ins.address:#08x} {ins.mnemonic:<8} {ins.op_str:<36} [{owner}]")
    print(f"   -> {hits} hit(s)")

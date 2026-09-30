#!/usr/bin/env python3
"""Annotated dump of an arbitrary sub9 address range (project root aware).

Usage: python _analysis/_zfz_range.py LO HI [ipa] > out.txt
"""
from __future__ import annotations

import pathlib as _pl
import sys

HERE = _pl.Path(__file__).resolve().parent
ROOT = next(p for p in [HERE, *HERE.parents] if (p / "tools" / "audit_zfr_ipa.py").exists())
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

from _t6_ann import Annotator, load  # noqa: E402

pos = [x for x in sys.argv[1:] if not x.startswith("--")]
IPA = next((x for x in pos[2:] if x.lower().endswith(".ipa")),
           str(ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"))
LO, HI = int(pos[0], 0), int(pos[1], 0)

a = Annotator(load(IPA, subtype=9))
a.dump_range(LO, HI)

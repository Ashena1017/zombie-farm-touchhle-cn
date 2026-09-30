#!/usr/bin/env python3
"""Full-__text scan for references to a selector, using annot_disasm's
register-tracking annotator (the simple PC-relative scan misses ARMv7 PIC
`movw/movt` + `add rX, pc` addressing).

Usage: scan_selector_refs.py incrementCount: [--ipa NAME] [--sub 6|9]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from annot_disasm import annotate, method_index  # noqa: E402
from audit_zfr_ipa import parse_fat  # noqa: E402
from inspect_v3_facts import EXECUTABLE, ROOT  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('selector')
    ap.add_argument('--ipa', default='Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa')
    ap.add_argument('--sub', type=int, default=None)
    a = ap.parse_args()

    with zipfile.ZipFile(ROOT / a.ipa) as z:
        fat = z.read(EXECUTABLE)
    for sl in parse_fat(fat):
        if a.sub is not None and sl.subtype != a.sub:
            continue
        thumb = sl.subtype == 9
        print(f'\n===== sub{sl.subtype} thumb={thumb} =====')
        txt = next(s for s in sl.sections if s.name == '__text')
        idx = method_index(sl)
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        md.skipdata = True
        regs = {}
        hit = 0
        for ins in md.disasm(sl.data[txt.offset:txt.offset + txt.size], txt.addr):
            if not ins.id:
                regs.clear()
                continue
            note = annotate(sl, ins, thumb, idx, regs)
            if a.selector in note:
                hit += 1
                at = ins.address & ~1
                prev = max((x for x in idx if x <= at), default=None)
                owner = ''
                if prev is not None and at - prev < 0x2000:
                    n, s, k = idx[prev]
                    owner = f'{n} {s} +{at - prev:#x}'
                print(f'   {ins.address:#08x} {ins.mnemonic:<8} {ins.op_str:<32} {note}   [{owner}]')
        print(f'  {hit} reference(s)')


if __name__ == '__main__':
    main()

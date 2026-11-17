"""Independently check product/flag bindings in both original Mach-O slices."""
import contextlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods
from annot_disasm import dump, method_index

EXPECTED = [
    ('skeletonHeadMaleSelected:', 1), ('vampireHeadMaleSelected:', 2),
    ('skeletonHeadFemaleSelected:', 4), ('vampireHeadFemaleSelected:', 8),
    ('zombieHeadMaleSelected:', 16), ('zombieHeadFemaleSelected:', 32),
    ('paperBagHeadMaleSelected:', 64), ('monolithHeadMaleSelected:', 128),
    ('pumpkinHeadMaleSelected:', 256),
]


def main():
    ipa = ROOT / 'zombie_farm_ipa' / (ROOT / 'launcher_selected_ipa.txt').read_text(encoding='utf-8-sig').strip()
    with zipfile.ZipFile(ipa) as z:
        slices = parse_fat(z.read('Payload/ZFR.app/ZFR'))
    rows = []
    for sl in slices:
        index = method_index(sl)
        starts = sorted(index)
        methods = {m.selector: m for m in all_methods(sl, *classes_by_name(sl)['ZFFarmerSelectionMenu'])}
        for number, (selector, mask) in enumerate(EXPECTED, 1):
            m = methods[selector]
            start = m.imp & ~1
            end = next(a for a in starts if a > start)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                dump(sl, start, end - start, bool(m.imp & 1), index)
            assembly = output.getvalue()
            tail = assembly.split("sel='fflags'", 1)[1].splitlines()[:5]
            expected = f'#{mask:#x}' if mask >= 10 else f'#{mask}'
            assert any('tst' in line and expected in line for line in tail), (sl.subtype, selector, tail)
            for suffix in ['', '_iPad']:
                assert f'CFSTR "com.playforge.ZombieFarm.FarmerHead{number}{suffix}"' in assembly
            rows.append({'slice': sl.subtype, 'product': number, 'selector': selector, 'flag': mask})
    out = ROOT / '_analysis/dumps/farmer-scroll-20261117/farmer-bindings.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding='utf-8')
    print(f'PASS: {len(rows)} farmer bindings across both slices; nine products, phone/tablet identifiers, original persistent flags')


if __name__ == '__main__':
    main()

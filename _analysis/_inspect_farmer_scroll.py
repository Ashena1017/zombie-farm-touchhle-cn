"""Read-only content/method inventory for the farmer purchase and scrolling fixes."""
import json
import plistlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from audit_zfr_ipa import parse_fat
from inspect_v3_facts import classes_by_name, all_methods, read_ivars
from annot_disasm import dump, method_index
import contextlib

ipa = next((ROOT / 'zombie_farm_ipa').glob('*v29fix.ipa'))
out = ROOT / '_analysis/dumps/farmer-scroll-20261117'
out.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(ipa) as z:
    names = z.namelist()
    assets = [n for n in names if any(s in n.lower() for s in ['farmer', 'head', 'mutat', 'inapp', 'product', 'digest']) and not n.endswith('.png')]
    print('IPA', ipa.name)
    print('ASSETS', '\n'.join(assets))
    for n in assets:
        if n.endswith('.plist'):
            try:
                p = plistlib.loads(z.read(n))
            except Exception:
                continue
            (out / (n.replace('/', '_') + '.json')).write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')
            print(n, repr(p)[:3500])
    slices = parse_fat(z.read('Payload/ZFR.app/ZFR'))
sl = next(s for s in slices if s.subtype == 9)
lines = []
for name, (cls, info) in classes_by_name(sl).items():
    if name in ('GameData', 'GameState', 'ZFAlertWindow', 'ZFGuiLayer') or any(s in name.lower() for s in ['farmer', 'head', 'table', 'scroll', 'mutat', 'purchase', 'product', 'store', 'invasion', 'zombiecell', 'zombiemenu']):
        lines.append(f'CLASS {name} {cls:#x} size={info["instance_size"]}')
        lines.extend('  IVAR ' + str(v) for v in read_ivars(sl, info['ivars']))
        lines.extend(f'  {m.imp:#x} {m.kind}{m.selector} {m.types}' for m in all_methods(sl, cls, info))
(out / 'methods.txt').write_text('\n'.join(lines), encoding='utf-8')
print('METHODS', out / 'methods.txt')
idx = method_index(sl)
starts = sorted(idx)
targets = {
    'ZFFarmerCell': ['setHeadID:'],
    'ZFFarmerSelectionMenu': ['table:cellTouched:', 'buyHead:', 'table:cellAtIndex:'] + [m.selector for m in all_methods(sl, *classes_by_name(sl)['ZFFarmerSelectionMenu']) if 'Selected:' in m.selector],
    'ZFMutationMenu': ['table:cellAtIndex:', 'refreshTable:'],
    'ZFZombieCell': ['setZombie:'],
    'ZFGuiLayer': ['updateBrains', 'displayAlertSimpleChoice:withMessage:withSprite:'],
    'GameState': ['subResource:amount:', 'hasResource:amount:'],
    'ZFAlertWindow': ['dismissAlertPositive:', 'dismissAlertNegative:'],
    'CCTableView': ['dequeueCell', '_moveCellOutOfSight:', '_evictCell', 'reloadData', 'scrollViewDidScroll:', '_addCellIfNecessary:'],
}
for name, selectors in targets.items():
    cls, info = classes_by_name(sl)[name]
    for m in all_methods(sl, cls, info):
        if m.selector not in selectors:
            continue
        start = m.imp & ~1
        end = next(s for s in starts if s > start)
        path = out / (name + '-' + m.selector.replace(':', '_') + '.txt')
        with path.open('w', encoding='utf-8') as f, contextlib.redirect_stdout(f):
            dump(sl, start, end - start, bool(m.imp & 1), idx)
print('DISASM', len(targets), 'classes')
for path in sorted(out.glob('ZFFarmerSelectionMenu-*Selected_.txt')):
    lines = path.read_text(encoding='utf-8').splitlines()
    print(path.stem)
    for l in lines:
        if 'tst' in l or 'FarmerHead' in l:
            print(l)

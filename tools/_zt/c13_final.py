"""DEFINITIVE census: every AlertWindow font site + provenance vs the 13-site table.

Two correctness features the earlier pass lacked:
  * arity-aware fontSize stack slot (CGSize eats two words, so the 5-arg
    dimensions form puts fontSize at [sp,#0xc], the 3-arg form at [sp,#0x0]).
  * FRESHNESS filter - a stack slot is only trusted if the store that produced
    it post-dates the previous msgSend in the same method.  Without this, a
    slot left over from an earlier call is misreported as this call's argument.
"""
import struct
import sys
import zt, zsel, zscan
from inspect_v3_facts import classes_by_name, all_methods, class_ro

IPA = sys.argv[1] if len(sys.argv) > 1 else \
    'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed.ipa'
ONLY = sys.argv[2] if len(sys.argv) > 2 else None

TABLE = {
    6: {0x0A040C, 0x0A0468, 0x0A04BC, 0x0A0F04, 0x0A1048, 0x0A16FC, 0x0A2190},
    9: {0x0748E6, 0x074936, 0x0750F8, 0x075200, 0x075788, 0x075FAA},
}
IN_SCOPE = {0x41700000: 15.0, 0x41A00000: 20.0, 0x41900000: 18.0,
            0x41C00000: 24.0}
SLOT = {
    'labelWithString:dimensions:alignment:fontName:fontSize:': 0xC,
    'initWithString:dimensions:alignment:fontName:fontSize:': 0xC,
    'labelWithString:dimensions:hAlignment:fontName:fontSize:': 0xC,
    'initWithString:dimensions:hAlignment:fontName:fontSize:': 0xC,
    'labelWithString:dimensions:hAlignment:vAlignment:fontName:fontSize:': 0x10,
    'labelWithString:fontName:fontSize:': 0x0,
    'initWithString:fontName:fontSize:': 0x0,
}


def fbits(v):
    if not isinstance(v, int):
        return None
    return struct.unpack('<f', struct.pack('<I', v & 0xFFFFFFFF))[0]


rows_out = []
sls = zsel.load_ipa(IPA)
print(f'### {IPA}   (ONLY={ONLY})\n')
for st in (6, 9):
    sl = sls[st]
    ctx = zscan.Ctx(sl)
    byname = classes_by_name(sl)
    starts = sorted({r[0] for r in ctx.rows})
    print(f'\n############ subtype {st} ############')
    for cn in sorted(n for n in byname if 'AlertWindow' in n):
        if ONLY and ONLY not in cn:
            continue
        cls, info = byname[cn]
        for m in sorted(all_methods(sl, cls, info), key=lambda x: x.imp):
            start = m.imp & ~1
            nxt = next((s for s in starts if s > start), None)
            end = min(nxt, start + 0x1600) if nxt else start + 0x1600
            try:
                calls, _ = zscan.scan_method(ctx, start, end)
            except Exception:
                continue
            prev = start
            for c in calls:
                sel = c['sel']
                if not sel:
                    prev = c['addr']
                    continue
                if sel not in SLOT and sel != 'setFontSize:':
                    prev = c['addr']
                    continue
                fresh = True
                if sel == 'setFontSize:':
                    r2 = c['regs'].get(zscan._argreg(ctx, 2))
                    bits = r2[1] if r2 and r2[0] == 'imm' else None
                    prov = c['rdef'].get(zscan._argreg(ctx, 2), [])
                    slotname = 'r2'
                else:
                    slot = SLOT[sel]
                    v = c['stack'].get(slot)
                    bits = v[1] if v and v[0] == 'imm' else None
                    prov = c['sdef'].get(slot, [])
                    slotname = f'[sp,#{slot:#x}]'
                    # freshness: the store must come after the previous call
                    fresh = bool(prov) and max(prov) > prev
                f = fbits(bits)
                inscope = isinstance(bits, int) and bits in IN_SCOPE and fresh
                covered = [p for p in prov if p in TABLE[st]]
                recv = c['recv']
                rtxt = f'{recv[0]}:{recv[1]}' if recv else '?'
                if isinstance(rtxt, str) and len(rtxt) > 26:
                    rtxt = rtxt[:26]
                rows_out.append((st, cn, m.kind, m.selector, c['addr'], sel,
                                 slotname, bits, f, prov, inscope, covered,
                                 fresh, rtxt))
                flag = ''
                if inscope and not covered:
                    flag = '   *** IN-SCOPE FONT, NOT IN TABLE ***'
                elif covered:
                    flag = f'   [table @ {[hex(x) for x in covered]}]'
                if not fresh:
                    flag += '  [STALE-SLOT/ignored]'
                print(f'  {cn:<40} [{m.kind:<8}] {m.selector[:30]:<30} '
                      f'call={c["addr"]:#08x} {sel[:26]:<26} {slotname}='
                      f'{("%#010x" % bits) if isinstance(bits, int) else "?":<12} '
                      f'f={f} recv={rtxt} prov={[hex(x) for x in prov]}{flag}')
                prev = c['addr']

print('\n\n########## MISSING: in-scope (15/20/18/24) sites NOT covered by table ##########')
for r in rows_out:
    (st, cn, kind, msel, ca, sel, slotname, bits, f, prov, inscope,
     covered, fresh, rtxt) = r
    if inscope and not covered:
        print(f'  sub{st} {cn} [{kind}] {msel} call={ca:#x} {sel} '
              f'{slotname}={bits:#010x} ({f}) recv={rtxt} '
              f'prov={[hex(x) for x in prov]}')
print('\n########## table entries never matched by any scanned site ##########')
matched = set()
for r in rows_out:
    for p in r[11]:
        matched.add((r[0], p))
for st in (6, 9):
    for a in sorted(TABLE[st]):
        if (st, a) not in matched:
            print(f'  sub{st} {a:#x} UNMATCHED by scanner')

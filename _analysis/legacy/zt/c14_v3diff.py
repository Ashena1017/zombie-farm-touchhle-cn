"""Byte-exact diff .fixed.ipa -> .fixed-fonts-v3.ipa, attributed to the 13 sites.

Also decodes each patched word in BOTH slices at its real address/mode so the
shipped result is checked against the file, not the table.
"""
import struct
import zipfile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
import zt  # sets sys.path so audit_zfr_ipa / inspect_v3_facts resolve
from zt import ROOT, EXECUTABLE, parse_fat

import pathlib
_R = pathlib.Path(str(ROOT))
A = _R / 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed.ipa'
B = _R / 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v3.ipa'

TABLE = [
    (6, 0x0A040C, '1a36a0e3', '1c36a0e3', 'initWithWindow: title1 20->24'),
    (6, 0x0A0468, '1726a0e3', '1926a0e3', 'initWithWindow: body1 15->18'),
    (6, 0x0A04BC, '1726a0e3', '1926a0e3', 'initWithWindow: body2 15->18'),
    (6, 0x0A0F04, 'c00ab8ee', '020ab3ee', 'alertWindowInformative body vcvt->vmov 18.0'),
    (6, 0x0A1048, 'c00ab8ee', '080ab3ee', 'alertWindowInformative title vcvt->vmov 24.0'),
    (6, 0x0A16FC, '1726a0e3', '1926a0e3', 'alertWindowSimple body1 15->18'),
    (6, 0x0A2190, '1736a0e3', '1936a0e3', 'alertWindowSimpleChoice body1 15->18'),
    (9, 0x0748E6, 'c4f2a011', 'c4f2c011', 'initWithWindow: title1 movt r1 20->24'),
    (9, 0x074936, 'c4f27016', 'c4f29016', 'initWithWindow: body1+body2 movt r6 15->18'),
    (9, 0x0750F8, 'bbff0006', 'b3ee020a', 'alertWindowInformative vcvt->vmov 18.0'),
    (9, 0x075200, 'bbff0006', 'b3ee080a', 'alertWindowInformative vcvt->vmov 24.0'),
    (9, 0x075788, 'c4f27012', 'c4f29012', 'alertWindowSimple movt r2 15->18'),
    (9, 0x075FAA, 'c4f27014', 'c4f29014', 'alertWindowSimpleChoice movt r4 15->18'),
]
FORBID = {6: (0x1B464, 0x1B810), 9: (0x14F6C, 0x151C0)}


def execbytes(p):
    with zipfile.ZipFile(p) as z:
        return z.read(EXECUTABLE)


da, db = execbytes(A), execbytes(B)
print(f'A len={len(da)}  B len={len(db)}  same_len={len(da) == len(db)}')

# raw runs over the whole FAT container
runs = []
i = 0
while i < min(len(da), len(db)):
    if da[i] != db[i]:
        j = i
        while j < min(len(da), len(db)) and da[j] != db[j]:
            j += 1
        runs.append((i, j))
        i = j
    else:
        i += 1
print(f'\ncontiguous differing runs (container file offsets): {len(runs)}, '
      f'total bytes={sum(j - i for i, j in runs)}')

sa = {s.subtype: s for s in parse_fat(da)}
sb = {s.subtype: s for s in parse_fat(db)}

# map each container-offset run to (subtype, vmaddr)
def locate(off):
    with zipfile.ZipFile(A) as z:
        pass
    for st in (6, 9):
        s = sa[st]
        # slice.data is the slice image; find its container base by search of
        # the FAT header instead: re-parse arch table.
        pass
    return None


nfat = struct.unpack_from('>I', da, 4)[0]
archs = []
for k in range(nfat):
    ct, cs, o, sz, al = struct.unpack_from('>5I', da, 8 + k * 20)
    archs.append((cs, o, sz))
print('fat arch table:', [(cs, hex(o), hex(sz)) for cs, o, sz in archs])

expected = set()
for st, addr, old, new, _ in TABLE:
    off = sa[st].addr_to_file(addr)
    base = next(o for cs, o, sz in archs if cs == st)
    for k in range(len(old) // 2):
        expected.add(base + off + k)

covered, stray = 0, []
for i, j in runs:
    for k in range(i, j):
        if k in expected:
            covered += 1
        else:
            stray.append(k)
print(f'\ndiffering bytes inside the 13 table sites : {covered}')
print(f'differing bytes OUTSIDE the 13 table sites: {len(stray)}'
      + (f'  {[hex(x) for x in stray[:20]]}' if stray else '  <-- none, clean'))

print('\n=== per-site byte + disassembly verification (read from both IPAs) ===')
ok = True
for st, addr, old, new, why in TABLE:
    s_a, s_b = sa[st], sb[st]
    off = s_a.addr_to_file(addr)
    n = len(old) // 2
    ga = s_a.data[off:off + n].hex()
    gb = s_b.data[off:off + n].hex()
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if st == 9 else CS_MODE_ARM)
    def dis(blob):
        for ins in md.disasm(blob, addr):
            return f'{ins.mnemonic} {ins.op_str}'
        return '<undecodable>'
    m_old, m_new = (ga == old), (gb == new)
    ok &= m_old and m_new
    lo, hi = FORBID[st]
    infb = lo <= addr < hi
    print(f'sub{st} {addr:#08x} off={off:#08x} A={ga} ({"OK" if m_old else "MISMATCH"})'
          f'  B={gb} ({"OK" if m_new else "MISMATCH"})  forbidden={infb}')
    print(f'      A: {dis(s_a.data[off:off + n])}')
    print(f'      B: {dis(s_b.data[off:off + n])}      # {why}')
print(f'\nALL 13 SITES AS SPECIFIED: {ok}')

print('\n=== forbidden ranges byte-identical between A and B? ===')
for st, (lo, hi) in FORBID.items():
    oa = sa[st].addr_to_file(lo)
    ob = sb[st].addr_to_file(lo)
    n = hi - lo
    same = sa[st].data[oa:oa + n] == sb[st].data[ob:ob + n]
    print(f'  sub{st} {lo:#x}..{hi:#x} ({n} bytes) identical={same}')

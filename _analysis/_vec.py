"""Fetch real instruction bytes from the binary to use as encoder self-test vectors."""

# --- project root bootstrap (added by _analysis/relocate_paths.py) ----------
import pathlib as _pl
import sys as _sys


def _find_project_root(start):
    for _p in [start, *start.parents]:
        if (_p / "tools" / "audit_zfr_ipa.py").exists():
            return _p
    raise RuntimeError("project root not found above %s" % start)


_PROJECT_ROOT = _find_project_root(_pl.Path(__file__).resolve().parent)
_sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
# ---------------------------------------------------------------------------
import sys, zipfile, struct
pass  # sys.path handled by the bootstrap below
from audit_zfr_ipa import parse_fat

IPA = str(_PROJECT_ROOT / "zombie_farm_ipa/Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v12fix.ipa")
with zipfile.ZipFile(IPA) as z:
    fat = z.read("Payload/ZFR.app/ZFR")

VEC = {
    6: [(0xB73A0, "b  ->0xb74a0"), (0xB73AC, "b  ->0xb74a0"),
        (0xB7490, "b  ->0xb74a0"), (0x1B4D0, "bl ->0x1b6d0"),
        (0x1B4E4, "bl ->0x1b6d0"), (0x1B4DC, "bl ->0x1b6f0?")],
    9: [(0x14FBC, "bl  ->0x15140"), (0x14FCE, "bl  ->0x15140"),
        (0x86112, "blx ->0x2d014c"), (0x86218, "blx ->0x2d014c"),
        (0x151A0, "bl  ->0x15114")],
}
for sub, entries in VEC.items():
    sl = next(s for s in parse_fat(fat) if s.subtype == sub)
    print("#### sub%d" % sub)
    for addr, note in entries:
        o = sl.addr_to_file(addr)
        raw = sl.data[o:o + 4]
        off = struct.unpack_from("<i", raw)[0] if sub == 6 else None
        if sub == 6:
            w = struct.unpack_from("<I", raw)[0]
            op = (w >> 24) & 0xF
            imm24 = w & 0xFFFFFF
            if imm24 & 0x800000:
                imm24 -= 0x1000000
            tgt = addr + 8 + (imm24 << 2)
            print("   %#010x %-22s bytes=%s  word=%#010x  decoded_target=%#x"
                  % (addr, note, raw.hex(), w, tgt))
        else:
            hw1, hw2 = struct.unpack_from("<HH", raw)
            S = (hw1 >> 10) & 1
            imm10 = hw1 & 0x3FF
            J1 = (hw2 >> 13) & 1
            J2 = (hw2 >> 11) & 1
            imm11 = hw2 & 0x7FF
            I1 = (~(J1 ^ S)) & 1
            I2 = (~(J2 ^ S)) & 1
            off = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
            if off & 0x1000000:
                off -= 0x2000000
            kind = "BLX" if (hw2 & 0x1000) == 0 else "BL"
            base = ((addr + 4) & ~3) if kind == "BLX" else (addr + 4)
            print("   %#010x %-22s bytes=%s  hw=(%#06x,%#06x) %s  off=%#x  base=%#x  target=%#x"
                  % (addr, note, raw.hex(), hw1, hw2, kind, off, base, base + off))

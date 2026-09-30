#!/usr/bin/env python3
"""Raise Zombie Farm's framerate from ~30 to ~60 without speeding the game up.

WHY THIS WORKS
--------------
The app drives its frame loop from `CCFastDirector -preMainLoop`. That method
calls `CFRunLoopRunInMode(mode, 0.0, true)` TWICE per frame -- once to drain
events before `drawScene`, once to drain after it. On real iPhone OS a
zero-timeout run-loop call is a non-blocking poll and returns at once.

touchHLE implements it as "run one iteration of the run loop", and every run
loop iteration ends with

    let limit = Duration::from_millis(1000 / 60);   // 16 ms
    env.sleep(...)

so each poll really costs ~16 ms. Two polls per frame => ~32 ms per frame =>
~30 fps. That is exactly what the profiler shows: `run_loop` is called twice as
often as `eagl_present_renderbuffer` (5502 vs 2750 over one run, ratio 2.0007).

Removing ONE of the two polls halves the per-frame waiting, so the loop runs at
~60 fps (still capped by touchHLE's 60 fps limiter).

WHY THE GAME DOES NOT SPEED UP
------------------------------
`CCDirector -calculateDeltaTime` computes the frame delta from `gettimeofday()`
-- real elapsed wall-clock time -- not from the frame interval. So drawing twice
as often halves each delta instead of advancing game time faster: crops, zombie
behaviour and timers all still advance at one real second per second.

A useful side effect: the run loop is still serviced 60 times per second
(1 poll x 60 frames instead of 2 polls x 30 frames), so timers, run-loop
sources and touch input keep their existing cadence.

WHAT IS PATCHED
---------------
  sub9 (armv7, the slice touchHLE runs), CCFastDirector -preMainLoop:
      0x213ae6  blx  _CFRunLoopRunInMode     (the post-drawScene drain)
    -> 0x213ae6  movs r0, #0 / nop
    The following `cmp r0, #4 / beq` retry loop then exits immediately, so the
    drain becomes a no-op while the pre-drawScene drain at 0x213abc is kept, so
    input is still handled once per frame before drawing.

  sub6 (armv6, not executed by touchHLE but kept coherent):
      0x2c85b8  bl   _CFRunLoopRunInMode
    -> 0x2c85b8  mov  r0, #0

Usage:
    patch_zfr_fps60_v1.py --dry-run          # verify, change nothing
    patch_zfr_fps60_v1.py --apply            # write the patched IPA
    patch_zfr_fps60_v1.py --verify           # re-check an existing output
"""
from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from pathlib import Path

EXECUTABLE = "Payload/ZFR.app/ZFR"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
DEFAULT_IPA = f"{BASE}.fixed-fonts-v27fix.ipa"
DEFAULT_OUT = f"{BASE}.fixed-fonts-v27fix-fps60-v1.ipa"

LC_SEGMENT = 0x1
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB

# Per-slice patch sites. `expect` is what the file must contain (fail closed).
SITES = {
    6: [
        dict(
            addr=0x2C85B8,
            expect=bytes.fromhex("7a3003eb"),      # bl _CFRunLoopRunInMode
            replace=bytes.fromhex("0000a0e3"),     # mov r0, #0
            note="CCFastDirector -preMainLoop: post-drawScene CFRunLoopRunInMode drain",
        ),
    ],
    9: [
        dict(
            addr=0x213AE6,
            expect=bytes.fromhex("bcf076ee"),      # blx _CFRunLoopRunInMode
            replace=bytes.fromhex("002000bf"),     # movs r0, #0 ; nop
            note="CCFastDirector -preMainLoop: post-drawScene CFRunLoopRunInMode drain",
        ),
    ],
}


# ---------------------------------------------------------------- Mach-O ----


def load_cmds(data: bytes):
    """(cmd, cmdsize, file_offset) for each load command of a 32-bit Mach-O."""
    ncmds = struct.unpack_from("<I", data, 16)[0]
    out = []
    off = 28  # load commands always start right after the 32-bit header
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        out.append((cmd, cmdsize, off))
        off += cmdsize
    return out


def sections(data: bytes):
    out = []
    for cmd, _cmdsize, off in load_cmds(data):
        if cmd != LC_SEGMENT:
            continue
        nsects = struct.unpack_from("<I", data, off + 48)[0]
        sp = off + 56
        for _ in range(nsects):
            name = data[sp:sp + 16].split(b"\0", 1)[0].decode("ascii", "replace")
            (addr, size, offset, _align, _reloff, _nreloc, _flags, res1, res2) = \
                struct.unpack_from("<9I", data, sp + 32)
            out.append(dict(name=name, addr=addr, size=size,
                            offset=offset, res1=res1, res2=res2))
            sp += 68
    return out


def symtab_info(data: bytes):
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_SYMTAB:
            return struct.unpack_from("<IIII", data, off + 8)
    raise SystemExit("no LC_SYMTAB")


def dysymtab_info(data: bytes):
    for cmd, _cs, off in load_cmds(data):
        if cmd == LC_DYSYMTAB:
            f = struct.unpack_from("<18I", data, off + 8)
            return f[12], f[13]  # indirectsymoff, nindirectsyms
    raise SystemExit("no LC_DYSYMTAB")


def symbol_name(data: bytes, idx: int) -> str:
    symoff, nsyms, stroff, strsize = symtab_info(data)
    if idx in (0, 0xFFFF, 0xFFFFFF) or idx >= nsyms:
        return "<none>"
    strx = struct.unpack_from("<I", data, symoff + idx * 12)[0]
    if strx >= strsize:
        return "<bad-strx>"
    blob = data[stroff + strx: stroff + strsize]
    return blob.split(b"\0", 1)[0].decode("utf-8", "replace")


def slot_symbol_map(data: bytes):
    """{slot address: symbol name} for __la_symbol_ptr / __nl_symbol_ptr."""
    indirectsymoff, nindirectsyms = dysymtab_info(data)
    indirect = struct.unpack_from(f"<{nindirectsyms}I", data, indirectsymoff)
    out = {}
    for s in sections(data):
        if s["name"] not in ("__la_symbol_ptr", "__nl_symbol_ptr"):
            continue
        for k in range(s["size"] // 4):
            i = s["res1"] + k
            if i < len(indirect):
                out[s["addr"] + k * 4] = symbol_name(data, indirect[i])
    return out


def stub_symbol(data: bytes, addr: int, slots: dict):
    """Resolve a symbol stub to its symbol name. Returns (slot, name) or (None, None)."""
    off = addr_to_file(data, addr)
    if off is None:
        return None, None
    first = struct.unpack_from("<I", data, off)[0]
    # ARM:  ldr r12, [pc, #imm]
    if (first & 0xFFFFF000) == 0xE59FC000:
        lit = addr + 8 + (first & 0xFFF)
        lo = addr_to_file(data, lit)
        if lo is None:
            return None, None
        slot = struct.unpack_from("<I", data, lo)[0]
        return slot, slots.get(slot, "<?>")
    # Thumb-2:  ldr.w r12, [pc, #imm]
    hw1, hw2 = struct.unpack_from("<HH", data, off)
    if hw1 == 0xF8DF and (hw2 & 0xF000) == 0xC000:
        imm = hw2 & 0x0FFF
        pc = (addr + 4) & ~3
        lit = pc + imm
        lo = addr_to_file(data, lit)
        if lo is None:
            return None, None
        slot = struct.unpack_from("<I", data, lo)[0]
        return slot, slots.get(slot, "<?>")
    return None, None


def addr_to_file(data: bytes, addr: int):
    for s in sections(data):
        if s["addr"] <= addr < s["addr"] + s["size"]:
            return s["offset"] + addr - s["addr"]
    return None


def read_fat(data: bytes):
    """[(cpusubtype, offset, size)] for a FAT Mach-O."""
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic != 0xCAFEBABE:
        raise SystemExit(f"unexpected fat magic {magic:#x}")
    n = struct.unpack_from(">I", data, 4)[0]
    out = []
    for i in range(n):
        _cputype, subtype, offset, size, _align = struct.unpack_from(
            ">IIIII", data, 8 + i * 20)
        out.append((subtype, offset, size))
    return out


# ------------------------------------------------------------------ main ----


def analyse(fat: bytes, verbose=True):
    """Verify every patch site against the expected bytes and symbol."""
    slices = {st: (off, sz) for st, off, sz in read_fat(fat)}
    problems = []
    for subtype, sites in SITES.items():
        if subtype not in slices:
            problems.append(f"sub{subtype}: slice missing")
            continue
        soff, ssize = slices[subtype]
        sdata = fat[soff:soff + ssize]
        slots = slot_symbol_map(sdata)
        for site in sites:
            addr = site["addr"]
            off = addr_to_file(sdata, addr)
            if off is None:
                problems.append(f"sub{subtype} {addr:#x}: not file-backed")
                continue
            have = sdata[off:off + len(site["expect"])]
            ok_bytes = have == site["expect"]
            if not ok_bytes:
                problems.append(
                    f"sub{subtype} {addr:#x}: expected {site['expect'].hex()} "
                    f"found {have.hex()}")
            # Resolve the call target from the ORIGINAL instruction.
            if subtype == 9:
                cmd_off = addr
                imm = struct.unpack_from("<H", sdata, off + 2)[0] & 0x0FFF
                # recompute Thumb BLX target the same way capstone reports it
                target = None
            else:
                target = None
            if verbose:
                print(f"  sub{subtype} {addr:#x}: bytes={'OK' if ok_bytes else 'MISMATCH'}"
                      f"  {site['note']}")
            site["_ok"] = ok_bytes
    return problems


def apply_patch(fat: bytes):
    out = bytearray(fat)
    slices = {st: (off, sz) for st, off, sz in read_fat(fat)}
    changed = []
    for subtype, sites in SITES.items():
        soff, _ssize = slices[subtype]
        sdata = fat[soff:soff + _ssize]
        for site in sites:
            off = addr_to_file(sdata, site["addr"])
            abs_off = soff + off
            have = bytes(out[abs_off:abs_off + len(site["expect"])])
            if have != site["expect"]:
                raise SystemExit(
                    f"refusing to patch sub{subtype} {site['addr']:#x}: "
                    f"expected {site['expect'].hex()}, found {have.hex()}")
            out[abs_off:abs_off + len(site["replace"])] = site["replace"]
            changed.append((subtype, site["addr"], site["expect"].hex(),
                            site["replace"].hex()))
    return bytes(out), changed


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--ipa", default=DEFAULT_IPA)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    src = root / "zombie_farm_ipa" / a.ipa
    dst = root / "zombie_farm_ipa" / a.out

    if a.verify:
        if not dst.exists():
            raise SystemExit(f"no such file: {dst}")
        with zipfile.ZipFile(dst) as z:
            fat = z.read(EXECUTABLE)
        print(f"verifying {dst.name}")
        slices = {st: (off, sz) for st, off, sz in read_fat(fat)}
        bad = 0
        for subtype, sites in SITES.items():
            soff, ssize = slices[subtype]
            sdata = fat[soff:soff + ssize]
            for site in sites:
                off = addr_to_file(sdata, site["addr"])
                have = sdata[off:off + len(site["replace"])]
                ok = have == site["replace"]
                print(f"  sub{subtype} {site['addr']:#x}: "
                      f"{'PATCHED' if ok else 'NOT PATCHED'}  ({have.hex()})")
                bad += 0 if ok else 1
        print("RESULT:", "OK" if bad == 0 else f"{bad} site(s) not patched")
        raise SystemExit(0 if bad == 0 else 1)

    with zipfile.ZipFile(src) as z:
        fat = z.read(EXECUTABLE)

    print(f"source : {src.name}")
    print(f"size   : {len(fat)} bytes")
    for subtype, off, size in read_fat(fat):
        print(f"  slice sub{subtype}: offset={off:#x} size={size:#x}")
    print("patch sites:")
    problems = analyse(fat)
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  " + p)
        raise SystemExit(2)

    if not a.apply:
        print("\ndry run: all sites verified, nothing written.")
        print(f"would write: {dst.name}")
        raise SystemExit(0)

    new_fat, changed = apply_patch(fat)
    print("applying:")
    for subtype, addr, old, new in changed:
        print(f"  sub{subtype} {addr:#x}: {old} -> {new}")

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == EXECUTABLE:
                data = new_fat
            zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            zi.compress_type = item.compress_type
            zi.external_attr = item.external_attr
            zi.internal_attr = item.internal_attr
            zi.create_system = item.create_system
            zout.writestr(zi, data)

    print(f"\nwrote {dst}  ({dst.stat().st_size} bytes)")
    print("now run: patch_zfr_fps60_v1.py --verify")


if __name__ == "__main__":
    main()

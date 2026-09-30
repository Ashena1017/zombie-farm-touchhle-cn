# -*- coding: utf-8 -*-
"""FAT-aware scan of the ZFR binary: locate ObjC classes owning zoom-related selectors."""
import re
import struct
import sys

BIN = sys.argv[1] if len(sys.argv) > 1 else r"<PATH-TO-EXTRACTED-ZFR-BIN>"
raw = open(BIN, "rb").read()

FAT_MAGIC = 0xCAFEBABE
magic, nfat = struct.unpack_from(">II", raw, 0)
assert magic == FAT_MAGIC, hex(magic)
slices = []
for i in range(nfat):
    cputype, subtype, off, size, align = struct.unpack_from(">IIIII", raw, 8 + i * 20)
    slices.append((cputype, subtype, off, size))
    print(f"slice {i}: cputype={cputype} subtype={subtype} off=0x{off:x} size=0x{size:x}")

# use the ARMv7 slice (subtype 9)
armv7 = [s for s in slices if s[1] == 9][0]
BASE = armv7[2]
data = raw[BASE:BASE + armv7[3]]
print(f"\nARMv7 slice: fileoff=0x{BASE:x} size=0x{len(data):x}")

m = struct.unpack_from("<I", data, 0)[0]
assert m == 0xFEEDFACE, hex(m)
cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags = struct.unpack_from("<6I", data, 4)
print(f"ncmds={ncmds} sizeofcmds=0x{sizeofcmds:x}")

off = 28
sections = []
segs = []
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack_from("<II", data, off)
    if cmd == 0x1:
        segname = data[off + 8:off + 24].rstrip(b"\0").decode("ascii", "replace")
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4I", data, off + 24)
        nsects = struct.unpack_from("<I", data, off + 48)[0]
        segs.append((segname, vmaddr, vmsize, fileoff, filesize))
        so = off + 56
        for _s in range(nsects):
            sectname = data[so:so + 16].rstrip(b"\0").decode("ascii", "replace")
            addr, size, offset = struct.unpack_from("<3I", data, so + 32)
            sections.append((segname, sectname, addr, size, offset))
            so += 68
    off += cmdsize

def va_to_off(va):
    for segname, vmaddr, vmsize, fileoff, filesize in segs:
        if vmaddr <= va < vmaddr + vmsize:
            return fileoff + (va - vmaddr)
    return None

def off_to_va(o):
    for segname, vmaddr, vmsize, fileoff, filesize in segs:
        if fileoff <= o < fileoff + filesize:
            return vmaddr + (o - fileoff)
    return None

def cstr(o):
    end = data.index(b"\0", o)
    return data[o:end].decode("ascii", "replace")

print("\n=== objc sections ===")
for segname, sectname, addr, size, offset in sections:
    if "objc" in sectname:
        print(f"  {segname:10s} {sectname:26s} addr=0x{addr:08x} size=0x{size:06x} off=0x{offset:08x}")

# ---- find classlist ----
classlist_sec = [s for s in sections if s[1] == "__objc_classlist"]
print("\nclasslist:", classlist_sec)

TARGETS = ["setZoomOutAmount:", "zoomFactor", "resetCameraWithZoom:", "scaleCompensation:",
           "initElementsWithWindowScale::atX:Y:", "scrollViewDidZoom:", "viewForZoomingInScrollView:"]

# Build va set of target selector string VAs
target_vas = {}
for t in TARGETS:
    for mm in re.finditer(re.escape(t.encode()) + b"\x00", data):
        va = off_to_va(mm.start())
        if va is not None:
            target_vas.setdefault(va, t)
print("\ntarget selector string VAs:")
for va, t in sorted(target_vas.items()):
    print(f"  0x{va:08x}  {t}")

# Build reverse map: selector-string VA -> list of file offsets of 32-bit pointers to it
ptr_sites = {}
for va, t in target_vas.items():
    ptr = struct.pack("<I", va)
    for mm in re.finditer(re.escape(ptr), data):
        ptr_sites.setdefault(mm.start(), []).append(t)

print(f"\npointer sites referencing target selectors: {len(ptr_sites)}")
for site, ts in sorted(ptr_sites.items()):
    sva = off_to_va(site)
    sec = next((s[1] for s in sections if s[4] <= site < s[4] + s[3]), "?")
    print(f"  0x{site:08x} (va 0x{sva:08x}) sec={sec:24s} -> {ts}")

# -*- coding: utf-8 -*-
"""Locate ObjC classes owning zoom-related selectors, and hunt for zoom UI text."""
import re
import struct
import sys

BIN = sys.argv[1] if len(sys.argv) > 1 else r"<PATH-TO-EXTRACTED-ZFR-BIN>"
data = open(BIN, "rb").read()

# ---- Mach-O header ----
magic = struct.unpack_from("<I", data, 0)[0]
print("magic 0x%08x" % magic)
cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags = struct.unpack_from("<6I", data, 4)
print("cputype=%d filetype=%d ncmds=%d" % (cputype, filetype, ncmds))

# ---- walk load commands ----
off = 28
sections = []
segs = []
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack_from("<II", data, off)
    if cmd == 0x19:  # LC_SEGMENT
        segname = data[off+8:off+24].rstrip(b"\0").decode("ascii", "replace")
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4I", data, off+24)
        nsects = struct.unpack_from("<I", data, off+48)[0]
        segs.append((segname, vmaddr, vmsize, fileoff, filesize))
        so = off + 56
        for _s in range(nsects):
            sectname = data[so:so+16].rstrip(b"\0").decode("ascii", "replace")
            segn = data[so+16:so+32].rstrip(b"\0").decode("ascii", "replace")
            addr, size, offset = struct.unpack_from("<3I", data, so+32)
            sections.append((segname, sectname, addr, size, offset))
            so += 68
    off += cmdsize

print("\n=== segments ===")
for s in segs:
    print("  %-12s vmaddr=0x%08x vmsize=0x%08x fileoff=0x%08x filesize=0x%08x" % s)

print("\n=== objc-related sections ===")
for segname, sectname, addr, size, offset in sections:
    if "objc" in sectname or "text" in sectname or "const" in sectname:
        print("  %-10s %-22s addr=0x%08x size=0x%08x off=0x%08x" % (segname, sectname, addr, size, offset))

def va_to_off(va):
    for segname, vmaddr, vmsize, fileoff, filesize in segs:
        if vmaddr <= va < vmaddr + vmsize:
            return fileoff + (va - vmaddr)
    return None

def cstr(off):
    end = data.index(b"\0", off)
    return data[off:end].decode("ascii", "replace")

# ---- find class names and their method lists ----
print("\n=== classes containing zoom-ish selectors ===")
TARGETS = ["setZoomOutAmount:", "zoomFactor", "resetCameraWithZoom:", "scaleCompensation:",
           "initElementsWithWindowScale::atX:Y:", "scrollViewDidZoom:", "viewForZoomingInScrollView:"]

# Build va->cstring map for selrefs
selref_sec = [s for s in sections if s[1] == "__objc_selrefs"]
print("selref sections:", selref_sec)

# Strategy: find every occurrence of the target selector cstring, then find
# pointers to that VA in __objc_selrefs / __objc_methname / data.
for t in TARGETS:
    print(f"\n--- {t} ---")
    for m in re.finditer(re.escape(t.encode()) + b"\x00", data):
        va = None
        for segname, vmaddr, vmsize, fileoff, filesize in segs:
            if fileoff <= m.start() < fileoff + filesize:
                va = vmaddr + (m.start() - fileoff)
                break
        if va is None:
            continue
        # find 32-bit little-endian pointers to this VA
        ptr = struct.pack("<I", va)
        refs = [mm.start() for mm in re.finditer(re.escape(ptr), data)]
        print(f"  str@0x{m.start():08x} va=0x{va:08x}  ptr_refs={len(refs)}")
        for r in refs[:8]:
            rva = None
            for segname, vmaddr, vmsize, fileoff, filesize in segs:
                if fileoff <= r < fileoff + filesize:
                    rva = vmaddr + (r - fileoff)
                    break
            sec = next((s[1] for s in sections if s[4] <= r < s[4] + s[3]), "?")
            print(f"      ref@0x{r:08x} va=0x{rva:08x} section={sec}")

# ---- UI text hunt ----
print("\n=== zoom-ish UI text ===")
for m in re.finditer(rb"[\x20-\x7e]{3,}", data):
    s = m.group().decode("ascii")
    low = s.lower()
    if any(k in low for k in ("zoom in", "zoom out", "pinch", "spread", "magnify")):
        print(f"  0x{m.start():08x}  {s[:130]}")

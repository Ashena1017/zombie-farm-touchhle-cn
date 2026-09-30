#!/usr/bin/env python3
r"""Is the VA-vs-file-offset skew global, or only in the data sections?

This matters enormously: if __text is skewed too, then EVERY disassembly address in
this project's reports could be off, including the ones the v28/v29 work relied on.

Facts to establish:
  * the slice's section table (addr vs file offset for each section);
  * whether addr_to_file(va) == va for __text;
  * what the ObjC method list says an IMP is, and whether code at that VA decodes
    as a plausible function prologue.

Read-only.
"""
from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from audit_zfr_ipa import parse_fat                      # noqa: E402
from patch_zfr_alert_fonts import EXECUTABLE             # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs      # noqa: E402

IPA = ROOT / "zombie_farm_ipa" / "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa"
with zipfile.ZipFile(IPA) as z:
    fat = z.read(EXECUTABLE)
sl = next(s for s in parse_fat(fat) if s.subtype == 9)
data = sl.data

print("=" * 78)
print("section table: VA vs file offset")
print("=" * 78)
print(f"  {'section':<20} {'VA':>10} {'file off':>10} {'delta':>8}  size")
for s in sl.sections:
    try:
        fo = sl.addr_to_file(s.addr)
    except Exception as exc:                              # noqa: BLE001
        print(f"  {s.name:<20} 0x{s.addr:08x}   <{exc}>")
        continue
    print(f"  {s.name:<20} 0x{s.addr:08x} 0x{fo:08x} 0x{s.addr - fo:08x}  0x{s.size:x}")

print()
print("=" * 78)
print("is __text skewed?")
print("=" * 78)
text = next(s for s in sl.sections if s.name == "__text")
tfo = sl.addr_to_file(text.addr)
print(f"  __text VA    = 0x{text.addr:08x}")
print(f"  __text file  = 0x{tfo:08x}")
print(f"  delta        = 0x{text.addr - tfo:x}")
print(f"  -> {'NOT skewed (VA == file offset)' if text.addr == tfo else 'SKEWED'}")

print()
print("=" * 78)
print("cross-check: a known method IMP should decode as a prologue")
print("=" * 78)
# ZFToolManager -popGameActionAndExecute:deltaTime: was reported at IMP 0x27939
# (odd => Thumb). Let's look at a few known IMPs from the method list.
from inspect_v3_facts import all_methods                  # noqa: E402

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

methods = list(all_methods(sl))
print(f"  {len(methods)} methods found")

# Find the one we care about.
want = None
for m in methods:
    nm = getattr(m, "name", None) or getattr(m, "sel", None) or ""
    cls = getattr(m, "cls", None) or getattr(m, "class_name", None) or ""
    if "popGameActionAndExecute" in str(nm) and "ToolManager" in str(cls):
        want = m
        break

if want is None:
    # fall back: scan for the selector string
    print("  (method not located by name; scanning __objc_methname)")
    idx = data.find(b"popGameActionAndExecute:deltaTime:")
    print(f"  selector string at file offset 0x{idx:x}")
else:
    print(f"  found: {want}")
    imp = getattr(want, "imp", None) or getattr(want, "addr", None)
    print(f"  IMP = 0x{imp:x}" if imp else "  (no imp attribute)")

# Directly: decode at VA 0x27938 using the CORRECT mapping.
print()
print("  decoding at VA 0x27938 via addr_to_file:")
off = sl.addr_to_file(0x27938)
print(f"    file offset = 0x{off:x}, first bytes = {data[off:off + 16].hex(' ')}")
for ins in md.disasm(data[off:off + 24], 0x27938):
    print(f"      0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

print()
print("  decoding at file offset 0x27938 directly (i.e. treating it as a VA):")
for ins in md.disasm(data[0x27938:0x27938 + 24], 0x27938):
    print(f"      0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}")

print()
print("=" * 78)
print("which one is real?  check for a push {...lr} prologue")
print("=" * 78)
for label, off in (("addr_to_file(0x27938)", sl.addr_to_file(0x27938)), ("raw 0x27938", 0x27938)):
    chunk = data[off:off + 8]
    ins = next(iter(md.disasm(chunk, 0x27938)), None)
    print(f"  {label:<26} {chunk.hex(' ')}  -> {ins.mnemonic} {ins.op_str}" if ins else f"  {label}: no decode")

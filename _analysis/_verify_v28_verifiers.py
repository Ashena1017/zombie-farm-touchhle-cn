#!/usr/bin/env python3
"""Mutation test for the v28 verifiers (READ-ONLY, writes nothing).

A verifier that never fails is worthless.  This script deliberately corrupts
the assembled bodies and the v27fix input in the exact ways that matter and
asserts that `patch_zfr_questfix_v28` rejects every one of them.

Instructions are located by decoding, not by byte-pattern search, so the test
stays correct if an encoding changes.
"""
from __future__ import annotations

import hashlib
import struct
import sys
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import patch_zfr_questfix_v28 as P  # noqa: E402
from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs  # noqa: E402
from patch_zfr_alert_fonts import EXECUTABLE, sha256  # noqa: E402


def find(body: bytes, base: int, mode, pred, nth: int = 0):
    """Return (offset, instruction) of the nth instruction matching pred."""
    md = Cs(CS_ARCH_ARM, mode)
    md.detail = True
    hits = [i for i in md.disasm(body, base) if pred(i)]
    if len(hits) <= nth:
        raise AssertionError(f"instruction not found (nth={nth}, hits={len(hits)})")
    i = hits[nth]
    return i.address - base, i


def expect_fail(label, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as ex:
        print(f"  caught  {label}: {type(ex).__name__}: {str(ex)[:88]}")
        return True
    print(f"  MISSED  {label}: verifier accepted corrupted input!")
    return False


def main() -> int:
    body9, code6, pool6 = P.assemble()
    ok = True

    print("== baseline ==")
    P.verify_sub9(body9)
    P.verify_sub6(code6, pool6)
    P.verify_stack_balance()
    print("  baseline passes all verifiers")

    print("\n== sub9 mutations ==")
    # 1. wrong selector slot: change the `count` movw immediate 0x3aa8 -> 0x3af6
    off, ins = find(body9, P.SUB9_BASE, CS_MODE_THUMB,
                    lambda i: i.mnemonic == "movw" and i.op_str == "r1, #0x3aa8")
    b = bytearray(body9)
    b[off + 3] = 0xF6
    ok &= expect_fail("sub9 wrong selector slot", P.verify_sub9, bytes(b))

    # 2. drop the per-requirement removeObserver call (nop the 6th blx)
    off, ins = find(body9, P.SUB9_BASE, CS_MODE_THUMB,
                    lambda i: i.mnemonic == "blx", nth=5)
    b = bytearray(body9)
    b[off:off + 4] = struct.pack("<HH", 0xBF00, 0xBF00)
    ok &= expect_fail("sub9 missing loop removeObserver", P.verify_sub9, bytes(b))

    # 3. break the loop back-edge
    off, ins = find(body9, P.SUB9_BASE, CS_MODE_THUMB, lambda i: i.mnemonic == "b")
    b = bytearray(body9)
    b[off:off + 2] = struct.pack("<H", 0xBF00)
    ok &= expect_fail("sub9 no back-edge", P.verify_sub9, bytes(b))

    # 4. unbalanced stack: nop the `add sp, #0xc`
    off, ins = find(body9, P.SUB9_BASE, CS_MODE_THUMB,
                    lambda i: i.mnemonic == "add" and i.op_str == "sp, #0xc")
    b = bytearray(body9)
    b[off:off + 2] = struct.pack("<H", 0xBF00)
    ok &= expect_fail("sub9 unbalanced stack", P.verify_stack_balance,
                      bytes(b), code6)

    # 5. wrong call target
    off, ins = find(body9, P.SUB9_BASE, CS_MODE_THUMB,
                    lambda i: i.mnemonic == "blx", nth=5)
    b = bytearray(body9)
    b[off + 2] = 0x70
    ok &= expect_fail("sub9 wrong call target", P.verify_sub9, bytes(b))

    print("\n== sub6 mutations ==")
    # 6. wrong pool word
    bad_pool = bytearray(pool6)
    bad_pool[4 * P.POOL6_INDEX["removeObserver"]] ^= 0x04
    ok &= expect_fail("sub6 wrong pool word", P.verify_sub6, code6, bytes(bad_pool))

    # 7. pool load pointing outside the pool
    off, ins = find(code6, P.SUB6_BASE, CS_MODE_ARM,
                    lambda i: i.mnemonic == "ldr" and "[pc," in i.op_str)
    b = bytearray(code6)
    b[off] = 0x08                       # ldr r0,[pc,...] -> imm out of range
    ok &= expect_fail("sub6 pool load out of range", P.verify_sub6, bytes(b), pool6)

    # 8. missing loop removeObserver call (6th bl)
    off, ins = find(code6, P.SUB6_BASE, CS_MODE_ARM,
                    lambda i: i.mnemonic == "bl", nth=5)
    b = bytearray(code6)
    b[off:off + 4] = struct.pack("<I", 0xE1A00000)
    ok &= expect_fail("sub6 missing loop removeObserver", P.verify_sub6, bytes(b), pool6)

    # 9. body touches SP
    b = bytearray(code6)
    b[0:4] = struct.pack("<I", 0xE24DD008)          # sub sp, sp, #8
    ok &= expect_fail("sub6 body touches SP", P.verify_stack_balance, body9, bytes(b))

    print("\n== guard / overlap / input checks ==")
    if len(P.GUARDS) != 3:
        print("  MISSED  guard table has %d entries" % len(P.GUARDS))
        ok = False
    else:
        print("  guard table has 3 exact regions (sub9 body, sub6 code, sub6 pool)")

    for subtype, lo, hi in ((9, P.SUB9_BASE, P.SUB9_END),
                            (6, P.SUB6_BASE, P.SUB6_CODE_END),
                            (6, P.SUB6_POOL, P.SUB6_END)):
        for flo, fhi in P.FORBIDDEN_PRIOR.get(subtype, []):
            if lo < fhi and flo < hi:
                print(f"  MISSED  region {lo:#x}..{hi:#x} overlaps {flo:#x}..{fhi:#x}")
                ok = False
    print("  no v28 region overlaps a prior-patch region")

    # 10. oversized body must be rejected by assemble()'s size check
    try:
        from keystone import KS_ARCH_ARM, KS_MODE_THUMB, Ks
        enc, _ = Ks(KS_ARCH_ARM, KS_MODE_THUMB).asm(
            P.sub9_source() + "\n" + "\n".join(["    nop"] * 200), P.SUB9_BASE)
        if len(enc) <= P.SUB9_END - P.SUB9_BASE:
            print("  MISSED  oversized body not detected")
            ok = False
        else:
            print("  caught  oversized sub9 body: %d bytes > %d"
                  % (len(enc), P.SUB9_END - P.SUB9_BASE))
    except Exception as ex:
        print("  caught  oversized sub9 body: %s" % str(ex)[:80])

    # 11. the real input must be the pinned v27fix
    with zipfile.ZipFile(P.ROOT / P.INPUT_NAME) as z:
        exe = z.read(EXECUTABLE)
    got = sha256(exe).upper()
    if got != P.INPUT_EXEC_SHA256:
        print("  MISSED  input executable sha %s != %s" % (got, P.INPUT_EXEC_SHA256))
        ok = False
    else:
        print("  input executable matches the pinned v27fix sha256")

    from audit_zfr_ipa import parse_fat
    slices = {s.subtype: s for s in parse_fat(exe)}
    for (subtype, lo, hi), want in P.GUARDS.items():
        sl = slices[subtype]
        raw = sl.data[sl.addr_to_file(lo):sl.addr_to_file(hi - 1) + 1]
        g = hashlib.sha256(raw).hexdigest()
        if g != want:
            print(f"  MISSED  guard {subtype} {lo:#x}..{hi:#x} sha {g}")
            ok = False
    print("  all 3 guard hashes match the real v27fix bytes")

    print("\nRESULT:", "PASS - every mutation was caught" if ok
          else "FAIL - at least one mutation slipped through")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

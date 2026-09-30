#!/usr/bin/env python3
"""Build the v2 alert-font patch for the already fixed ZFR IPA.

The old font patch changed literal constants in ``ZFAlertWindow``.  Those
constants are not on the display path used by the three requested dialogs.
This patch wraps the four alert factory calls instead.  The wrapper calls the
original factory, adjusts the returned ``title1``/``body1``/``body2`` labels,
and calls the original strings' ``setString:`` again so Cocos rebuilds the
text textures.

Only ``Payload/ZFR.app/ZFR`` is changed.  The ZIP writer below edits the
existing archive bytes in place in memory: the replacement DEFLATE stream is
padded to the source member's exact compressed length, so every byte outside
the target member's CRC fields and compressed payload remains identical.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any

from audit_zfr_ipa import parse_fat


EXECUTABLE = "Payload/ZFR.app/ZFR"
EXPECTED_INPUT_NAME = "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed.ipa"
FAT_MAGIC = 0xCAFEBABE
ARM_CPU_TYPE = 12

OBJC_MSG_SEND = {6: 0x393FE0, 9: 0x2D014C}
HELPER_PLUS3 = {6: 0x1B690, 9: 0x15114}

TARGET_SELECTORS = {"showRateIt", "showTreeWorldPopUp"}
EXPECTED_METHOD_IMPS = {
    6: {"showRateIt": 0x1B464, "showTreeWorldPopUp": 0x1B688},
    9: {"showRateIt": 0x14F6D, "showTreeWorldPopUp": 0x15111},
}

# The four calls are the actual alert factory calls, not the earlier
# initWithWindow: calls inside those factories.
CALL_PATCHES: dict[int, list[dict[str, Any]]] = {
    6: [
        {
            "address": 0x1FFC8,
            "name": "invasion_simple",
            "wrapper": "two",
            "old": "04d00deb",
            "new": "d6edffeb",
        },
        {
            "address": 0x203F4,
            "name": "invasion_informative",
            "wrapper": "two",
            "old": "f9ce0deb",
            "new": "cbecffeb",
        },
        {
            "address": 0x20914,
            "name": "level_up",
            "wrapper": "three",
            "old": "b1cd0deb",
            "new": "9bebffeb",
        },
        {
            "address": 0xFFC78,
            "name": "zombie_camera",
            "wrapper": "two",
            "old": "d8500aeb",
            "new": "aa6efceb",
        },
    ],
    9: [
        {
            "address": 0x18790,
            "name": "invasion_simple",
            "wrapper": "two",
            "old": "b7f2dcec",
            "new": "fcf7d4fc",
        },
        {
            "address": 0x18B04,
            "name": "invasion_informative",
            "wrapper": "two",
            "old": "b7f222eb",
            "new": "fcf71afb",
        },
        {
            "address": 0x18F28,
            "name": "level_up",
            "wrapper": "three",
            "old": "b7f210e9",
            "new": "fcf724f9",
        },
        {
            "address": 0xBBB18,
            "name": "zombie_camera",
            "wrapper": "two",
            "old": "14f218eb",
            "new": "59f710fb",
        },
    ],
}

# These are the exact pre-patch regions in the verified .fixed.ipa.  Hashing
# the regions protects the code caves and the +3 helper from an accidental
# patch against a different executable revision.
REGION_GUARDS: dict[int, list[tuple[str, int, int, str]]] = {
    6: [
        (
            "helper_plus3",
            0x1B690,
            0x1B6C4,
            "40789498e6a15daf0bc6eecd0371d0b5117478961d6a234bb5ceb830311a958e",
        ),
        (
            "two_label_cave",
            0x1B728,
            0x1B784,
            "fe8e9bb7135e146b4856e513096d8e2633bd4a214802b98fe7a04c0dd7ce797a",
        ),
        (
            "cave_gap",
            0x1B784,
            0x1B788,
            "487d96356744c11aa8e76bac8087f4365cae16fdee66d4aea7cdd030f354e44b",
        ),
        (
            "three_label_cave",
            0x1B788,
            0x1B800,
            "7ff6e391f1f34e3d47238b6e2139db500ea7ddf8c5265aaabdc1bc07ddeea7fa",
        ),
    ],
    9: [
        (
            "helper_plus3",
            0x15114,
            0x1513C,
            "07250d37e951753bb267eac5a706a71bfc342b5a968d44c18959d194e5f3d493",
        ),
        (
            "two_label_cave",
            0x1513C,
            0x15174,
            "8356464eec1139c80761e04a5fc3bcee247c59df54cac69463d8cf36c42a1af8",
        ),
        (
            "three_label_cave",
            0x15174,
            0x151BE,
            "d50e9e02d67b88613d1d546b9214521ada3490d6a4b0d672e3da823b1848a56d",
        ),
    ],
}

# ARM wrappers use the old unreachable promotion-method bodies as code caves.
# The first ARMv6 three-label branch is deliberately local to the wrapper;
# the old draft incorrectly branched into the remaining obsolete method body.
WRAPPERS: dict[int, dict[str, dict[str, Any]]] = {
    6: {
        "two": {
            "address": 0x1B728,
            "data": bytes.fromhex(
                "f0402de90240a0e10350a0e114609de504d04de200608de5"
                "26e20deb04d08de20060a0e1000056e30a00000ad00096e5"
                "000050e30700000a0420a0e1c9ffffebd40096e5000050e3"
                "0200000a0520a0e1c4ffffeb0600a0e1f080bde8"
            ),
        },
        "three": {
            "address": 0x1B788,
            "data": bytes.fromhex(
                "f0402de90240a0e10350a0e114609de518709de508d04de2"
                "00608de504708de50ce20deb08d08de20070a0e1000057e3"
                "0f00000ad00097e5000050e30300000a0420a0e1afffffeb"
                "d40097e5000050e30700000a0520a0e1aaffffebd80097e5"
                "000050e30200000a0620a0e1a5ffffeb0700a0e1f080bde8"
            ),
        },
    },
    9: {
        "two": {
            "address": 0x1513C,
            "data": bytes.fromhex(
                "f0b514461d46059e81b00096bbf200e801b00646002e0dd0"
                "d6f8d000002809d02246fff7d9ffd6f8d400002802d02a46"
                "fff7d2ff3046f0bd"
            ),
        },
        "three": {
            "address": 0x15174,
            # Includes the required mov r5, r3.  Its presence keeps body1
            # alive across the objc_msgSend call.
            "data": bytes.fromhex(
                "f0b514461d46059e069f82b000960197baf2e2ef02b00746"
                "002f15d0d7f8d000002811d02246fff7bbffd7f8d40000280"
                "ad02a46fff7b4ffd7f8d800002803d03246fff7adff3846f0bd"
            ),
        },
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def arm_bl_target(data: bytes, base: int, offset: int) -> int:
    word = struct.unpack_from("<I", data, offset)[0]
    if word & 0x0F000000 != 0x0B000000:
        raise ValueError(f"expected ARM BL at {base + offset:#x}, got {word:08x}")
    imm = sign_extend(word & 0x00FFFFFF, 24)
    return base + offset + 8 + (imm << 2)


def thumb_bl_target(data: bytes, base: int, offset: int, blx: bool) -> int:
    first, second = struct.unpack_from("<HH", data, offset)
    if first & 0xF800 != 0xF000:
        raise ValueError(f"expected Thumb branch at {base + offset:#x}")
    expected_second = 0xC000 if blx else 0xD000
    if second & 0xD000 != expected_second or (blx and second & 1):
        raise ValueError(f"unexpected Thumb branch form at {base + offset:#x}")
    s = (first >> 10) & 1
    j1 = (second >> 13) & 1
    j2 = (second >> 11) & 1
    i1 = (~(j1 ^ s)) & 1
    i2 = (~(j2 ^ s)) & 1
    imm10 = first & 0x03FF
    # Both encodings carry imm11 in bits 10:0.  BLX differs only in the
    # aligned PC base and in requiring the low target bits to be zero.
    imm11 = second & 0x07FF
    shift = 1
    raw = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << shift)
    delta = sign_extend(raw, 25)
    pc = base + offset + 4
    if blx:
        pc &= ~3
    return pc + delta


def thumb_beq_target(data: bytes, base: int, offset: int) -> int:
    half = struct.unpack_from("<H", data, offset)[0]
    if half & 0xFF00 != 0xD000:
        raise ValueError(f"expected Thumb BEQ at {base + offset:#x}")
    return base + offset + 4 + sign_extend((half & 0xFF) << 1, 9)


def fat_descriptors(data: bytes) -> list[dict[str, int]]:
    if len(data) < 8:
        raise ValueError("executable is shorter than a FAT header")
    magic, nfat = struct.unpack_from(">II", data, 0)
    if magic != FAT_MAGIC:
        raise ValueError(f"expected FAT_MAGIC, got {magic:#x}")
    if nfat != 2:
        raise ValueError(f"expected exactly two FAT slices, found {nfat}")
    header_end = 8 + nfat * 20
    if len(data) < header_end:
        raise ValueError("truncated FAT architecture table")
    records: list[dict[str, int]] = []
    for index in range(nfat):
        cputype, subtype, offset, size, align = struct.unpack_from(
            ">IIIII", data, 8 + index * 20
        )
        if cputype != ARM_CPU_TYPE:
            raise ValueError(f"slice {index}: unexpected CPU type {cputype}")
        if subtype not in (6, 9):
            raise ValueError(f"slice {index}: unexpected CPU subtype {subtype}")
        if align > 31 or offset % (1 << align) != 0:
            raise ValueError(f"slice {index}: invalid FAT alignment/offset")
        if offset < header_end or size == 0 or offset + size > len(data):
            raise ValueError(f"slice {index}: FAT range is outside the executable")
        if data[offset : offset + 4] != b"\xce\xfa\xed\xfe":
            raise ValueError(f"slice {index}: missing 32-bit little-endian Mach-O magic")
        records.append(
            {
                "index": index,
                "cputype": cputype,
                "subtype": subtype,
                "offset": offset,
                "size": size,
                "align": align,
            }
        )
    if {r["subtype"] for r in records} != {6, 9}:
        raise ValueError("FAT file must contain one ARMv6 and one ARMv7 slice")
    ordered = sorted(records, key=lambda r: r["offset"])
    for left, right in zip(ordered, ordered[1:]):
        if left["offset"] + left["size"] > right["offset"]:
            raise ValueError("FAT slices overlap")
    return records


def target_methods(sl: Any) -> dict[str, Any]:
    found = [
        m
        for m in sl.methods
        if m.cls == "ZFGuiLayer"
        and m.kind == "instance"
        and m.selector in TARGET_SELECTORS
    ]
    if len(found) != 2 or {m.selector for m in found} != TARGET_SELECTORS:
        raise ValueError("expected exactly the two ZFGuiLayer promotion methods")
    return {m.selector: m for m in found}


def verify_existing_crash_fix(sl: Any, slice_index: int) -> list[dict[str, Any]]:
    methods = target_methods(sl)
    expected_imps = EXPECTED_METHOD_IMPS[sl.subtype]
    result: list[dict[str, Any]] = []
    for selector in sorted(TARGET_SELECTORS):
        method = methods[selector]
        if method.types != "v8@0:4":
            raise ValueError(
                f"slice {slice_index}: {selector} has unexpected type {method.types!r}"
            )
        expected_imp = expected_imps[selector]
        if method.imp != expected_imp:
            raise ValueError(
                f"slice {slice_index}: {selector} IMP {method.imp:#x} != {expected_imp:#x}"
            )
        start = method.imp & ~1
        offset = sl.addr_to_file(start)
        if offset is None:
            raise ValueError(f"slice {slice_index}: {selector} is not file-backed")
        expected = bytes.fromhex("704700bf" if sl.subtype == 9 else "1eff2fe10000a0e1")
        actual = sl.data[offset : offset + len(expected)]
        if actual != expected:
            raise ValueError(
                f"slice {slice_index}: existing fix for {selector} is absent or changed: "
                f"{actual.hex()} != {expected.hex()}"
            )
        result.append(
            {
                "selector": selector,
                "imp": method.imp,
                "file_offset": offset,
                "bytes": actual.hex(),
            }
        )
    return result


def region_bytes(sl: Any, start: int, end: int) -> bytes:
    first = sl.addr_to_file(start)
    last = sl.addr_to_file(end - 1)
    if first is None or last is None or last < first:
        raise ValueError(f"region {start:#x}-{end:#x} is not file-backed")
    return sl.data[first : last + 1]


def verify_region_guards(sl: Any, slice_index: int) -> list[dict[str, Any]]:
    result = []
    for name, start, end, expected_hash in REGION_GUARDS[sl.subtype]:
        actual = region_bytes(sl, start, end)
        digest = hashlib.sha256(actual).hexdigest()
        if digest.lower() != expected_hash.lower():
            raise ValueError(
                f"slice {slice_index}: {name} guard mismatch: {digest} != {expected_hash}"
            )
        result.append(
            {"name": name, "address": start, "end": end, "sha256": digest}
        )
    return result


def verify_call_sites(sl: Any, slice_index: int, patched: bool = False) -> list[dict[str, Any]]:
    result = []
    for spec in CALL_PATCHES[sl.subtype]:
        offset = sl.addr_to_file(int(spec["address"]))
        if offset is None:
            raise ValueError(
                f"slice {slice_index}: call address {int(spec['address']):#x} is not file-backed"
            )
        expected = bytes.fromhex(str(spec["new"] if patched else spec["old"]))
        actual = sl.data[offset : offset + len(expected)]
        if actual != expected:
            phase = "patched" if patched else "original"
            raise ValueError(
                f"slice {slice_index}: {phase} bytes at {int(spec['address']):#x}: "
                f"{actual.hex()} != {expected.hex()}"
            )
        result.append(
            {
                "name": spec["name"],
                "address": int(spec["address"]),
                "wrapper": spec["wrapper"],
                "bytes": actual.hex(),
            }
        )
    return result


def verify_wrapper_branches(
    subtype: int, name: str, address: int, data: bytes
) -> list[dict[str, Any]]:
    helper = HELPER_PLUS3[subtype]
    objc = OBJC_MSG_SEND[subtype]
    branches: list[tuple[str, int, int]] = []
    if subtype == 6 and name == "two":
        branches = [
            ("arm_bl", 0x18, objc),
            ("arm_beq", 0x28, address + 0x58),
            ("arm_beq", 0x34, address + 0x58),
            ("arm_bl", 0x3C, helper),
            ("arm_bl", 0x50, helper),
        ]
    elif subtype == 6 and name == "three":
        branches = [
            ("arm_bl", 0x20, objc),
            ("arm_beq", 0x30, address + 0x74),
            ("arm_beq", 0x3C, address + 0x50),
            ("arm_bl", 0x44, helper),
            ("arm_beq", 0x50, address + 0x74),
            ("arm_bl", 0x58, helper),
            ("arm_beq", 0x64, address + 0x74),
            ("arm_bl", 0x6C, helper),
        ]
    elif subtype == 9 and name == "two":
        branches = [
            ("thumb_blx", 0x0C, objc),
            ("thumb_beq", 0x16, address + 0x34),
            ("thumb_beq", 0x1E, address + 0x34),
            ("thumb_bl", 0x22, helper),
            ("thumb_beq", 0x2C, address + 0x34),
            ("thumb_bl", 0x30, helper),
        ]
    elif subtype == 9 and name == "three":
        branches = [
            ("thumb_blx", 0x10, objc),
            ("thumb_beq", 0x1A, address + 0x48),
            ("thumb_beq", 0x22, address + 0x48),
            ("thumb_bl", 0x26, helper),
            ("thumb_beq", 0x30, address + 0x48),
            ("thumb_bl", 0x34, helper),
            ("thumb_beq", 0x3E, address + 0x48),
            ("thumb_bl", 0x42, helper),
        ]
    else:
        raise ValueError(f"unknown wrapper {subtype}:{name}")

    result = []
    for kind, offset, expected_target in branches:
        if kind == "arm_bl":
            actual_target = arm_bl_target(data, address, offset)
        elif kind == "thumb_blx":
            actual_target = thumb_bl_target(data, address, offset, True)
        elif kind == "thumb_bl":
            actual_target = thumb_bl_target(data, address, offset, False)
        elif kind == "arm_beq":
            word = struct.unpack_from("<I", data, offset)[0]
            if word & 0xFF000000 != 0x0A000000:
                raise ValueError(f"expected ARM BEQ at {address + offset:#x}")
            actual_target = address + offset + 8 + (sign_extend(word & 0x00FFFFFF, 24) << 2)
        else:
            actual_target = thumb_beq_target(data, address, offset)
        if actual_target != expected_target:
            raise ValueError(
                f"{subtype}:{name} branch at {address + offset:#x} targets "
                f"{actual_target:#x}, expected {expected_target:#x}"
            )
        result.append(
            {
                "kind": kind,
                "address": address + offset,
                "target": actual_target,
            }
        )
    return result


def patch_fat_executable(original: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    descriptors = fat_descriptors(original)
    slices = parse_fat(original)
    if len(slices) != len(descriptors):
        raise ValueError("FAT parser returned an unexpected slice count")

    audit: list[dict[str, Any]] = []
    for index, (desc, sl) in enumerate(zip(descriptors, slices)):
        if sl.subtype != desc["subtype"] or len(sl.data) != desc["size"]:
            raise ValueError(f"slice {index}: FAT descriptor/parser mismatch")
        crash = verify_existing_crash_fix(sl, index)
        guards = verify_region_guards(sl, index)
        calls = verify_call_sites(sl, index, patched=False)
        wrappers = []
        for name, spec in WRAPPERS[sl.subtype].items():
            address = int(spec["address"])
            data = bytes(spec["data"])
            offset = sl.addr_to_file(address)
            if offset is None or offset + len(data) > len(sl.data):
                raise ValueError(f"slice {index}: wrapper {name} is not file-backed")
            wrappers.append(
                {
                    "name": name,
                    "address": address,
                    "length": len(data),
                    "sha256": sha256(data),
                    "branch_targets": verify_wrapper_branches(
                        sl.subtype, name, address, data
                    ),
                }
            )
        audit.append(
            {
                "slice": index,
                "subtype": sl.subtype,
                "fat_offset": desc["offset"],
                "fat_size": desc["size"],
                "existing_crash_fix": crash,
                "region_guards": guards,
                "call_sites": calls,
                "wrappers": wrappers,
            }
        )

    patched = bytearray(original)
    for index, (desc, sl) in enumerate(zip(descriptors, slices)):
        slice_offset = desc["offset"]
        for name, spec in WRAPPERS[sl.subtype].items():
            rel = sl.addr_to_file(int(spec["address"]))
            assert rel is not None
            data = bytes(spec["data"])
            absolute = slice_offset + rel
            original_region = region_bytes(
                sl, int(spec["address"]), int(spec["address"]) + len(data)
            )
            if bytes(patched[absolute : absolute + len(data)]) != original_region:
                raise ValueError(f"slice {index}: wrapper cave changed during patch")
            patched[absolute : absolute + len(data)] = data
        for call in CALL_PATCHES[sl.subtype]:
            rel = sl.addr_to_file(int(call["address"]))
            assert rel is not None
            absolute = slice_offset + rel
            old = bytes.fromhex(str(call["old"]))
            new = bytes.fromhex(str(call["new"]))
            if bytes(patched[absolute : absolute + len(old)]) != old:
                raise ValueError(f"slice {index}: call bytes changed during patch")
            if len(old) != len(new):
                raise ValueError("call replacement changes instruction width")
            patched[absolute : absolute + len(new)] = new
    return bytes(patched), audit


def verify_patched_fat(data: bytes) -> dict[str, Any]:
    descriptors = fat_descriptors(data)
    slices = parse_fat(data)
    if len(slices) != 2:
        raise ValueError("patched executable lost a FAT slice")
    slice_results = []
    for index, (desc, sl) in enumerate(zip(descriptors, slices)):
        if sl.subtype != desc["subtype"]:
            raise ValueError(f"slice {index}: subtype changed")
        verify_existing_crash_fix(sl, index)
        helper_guard = next(
            item for item in REGION_GUARDS[sl.subtype] if item[0] == "helper_plus3"
        )
        helper_actual = region_bytes(sl, helper_guard[1], helper_guard[2])
        if hashlib.sha256(helper_actual).hexdigest().lower() != helper_guard[3].lower():
            raise ValueError(f"slice {index}: +3 helper changed")
        wrapper_results = []
        for name, spec in WRAPPERS[sl.subtype].items():
            address = int(spec["address"])
            expected = bytes(spec["data"])
            offset = sl.addr_to_file(address)
            assert offset is not None
            actual = sl.data[offset : offset + len(expected)]
            if actual != expected:
                raise ValueError(f"slice {index}: wrapper {name} did not verify")
            wrapper_results.append(
                {
                    "name": name,
                    "address": address,
                    "length": len(expected),
                    "sha256": sha256(actual),
                    "branch_targets": verify_wrapper_branches(
                        sl.subtype, name, address, actual
                    ),
                }
            )
        calls = verify_call_sites(sl, index, patched=True)
        call_results = []
        for spec, call in zip(CALL_PATCHES[sl.subtype], calls):
            offset = sl.addr_to_file(int(spec["address"]))
            assert offset is not None
            if sl.subtype == 6:
                target = arm_bl_target(
                    sl.data, int(spec["address"]) - offset, offset
                )
            else:
                target = thumb_bl_target(
                    sl.data, int(spec["address"]) - offset, offset, False
                )
            wrapper_address = int(
                WRAPPERS[sl.subtype][str(spec["wrapper"])] ["address"]
            )
            if target != wrapper_address:
                raise ValueError(
                    f"slice {index}: {spec['name']} branch target {target:#x} "
                    f"!= wrapper {wrapper_address:#x}"
                )
            call_results.append({**call, "target": target})
        slice_results.append(
            {
                "slice": index,
                "subtype": sl.subtype,
                "existing_crash_fix_verified": True,
                "wrappers": wrapper_results,
                "call_sites": call_results,
            }
        )
    return {
        "fat_macho_reparsed": True,
        "slice_count": len(slices),
        "subtypes": [sl.subtype for sl in slices],
        "existing_crash_fix_verified": True,
        "wrapper_branches_verified": True,
        "call_site_targets_verified": True,
        "slices": slice_results,
    }


def find_eocd(raw: bytes) -> tuple[int, tuple[int, ...]]:
    start = max(0, len(raw) - (0xFFFF + 22))
    position = raw.rfind(b"PK\x05\x06", start)
    if position < 0 or position + 22 > len(raw):
        raise ValueError("ZIP end-of-central-directory record is missing")
    fields = struct.unpack_from("<IHHHHIIH", raw, position)
    comment_length = fields[7]
    if position + 22 + comment_length != len(raw):
        raise ValueError("ZIP EOCD comment/trailing bytes are inconsistent")
    return position, fields


def parse_zip_layout(raw: bytes) -> dict[str, Any]:
    eocd_offset, eocd = find_eocd(raw)
    _, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, _comment_len = eocd
    if disk != 0 or cd_disk != 0 or n_disk != n_total:
        raise ValueError("multi-disk ZIP archives are unsupported")
    if n_total == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        raise ValueError("ZIP64 archives are unsupported for raw member surgery")
    if cd_offset + cd_size != eocd_offset:
        raise ValueError("central-directory range does not end at EOCD")

    records: list[dict[str, Any]] = []
    cursor = cd_offset
    target: dict[str, Any] | None = None
    for index in range(n_total):
        if cursor + 46 > len(raw) or raw[cursor : cursor + 4] != b"PK\x01\x02":
            raise ValueError(f"central-directory entry {index} is malformed")
        fields = struct.unpack_from("<I6H3I5H2I", raw, cursor)
        (
            _sig,
            made,
            needed,
            flag,
            method,
            mtime,
            mdate,
            crc,
            csize,
            usize,
            name_len,
            extra_len,
            entry_comment_len,
            disk_start,
            int_attr,
            ext_attr,
            local_offset,
        ) = fields
        end = cursor + 46 + name_len + extra_len + entry_comment_len
        if end > len(raw):
            raise ValueError(f"central-directory entry {index} is truncated")
        name_bytes = raw[cursor + 46 : cursor + 46 + name_len]
        encoding = "utf-8" if flag & 0x800 else "cp437"
        try:
            name = name_bytes.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ValueError(f"central-directory entry {index} has invalid name") from exc
        record = {
            "index": index,
            "offset": cursor,
            "end": end,
            "name": name,
            "name_bytes": name_bytes,
            "flag": flag,
            "method": method,
            "crc": crc,
            "csize": csize,
            "usize": usize,
            "name_len": name_len,
            "extra_len": extra_len,
            "comment_len": entry_comment_len,
            "local_offset": local_offset,
            "made": made,
            "needed": needed,
            "mtime": mtime,
            "mdate": mdate,
            "disk_start": disk_start,
            "int_attr": int_attr,
            "ext_attr": ext_attr,
        }
        records.append(record)
        if name == EXECUTABLE:
            if target is not None:
                raise ValueError("target executable appears more than once in ZIP")
            target = record
        cursor = end
    if cursor != cd_offset + cd_size:
        raise ValueError("central-directory size does not match its entries")
    if target is None:
        raise ValueError(f"ZIP member {EXECUTABLE!r} is missing")

    local = int(target["local_offset"])
    if local + 30 > len(raw) or raw[local : local + 4] != b"PK\x03\x04":
        raise ValueError("target local header is malformed")
    local_fields = struct.unpack_from("<I5H3I2H", raw, local)
    (
        _sig,
        local_needed,
        local_flag,
        local_method,
        local_mtime,
        local_mdate,
        local_crc,
        local_csize,
        local_usize,
        local_name_len,
        local_extra_len,
    ) = local_fields
    local_name_start = local + 30
    local_data_start = local_name_start + local_name_len + local_extra_len
    local_data_end = local_data_start + int(target["csize"])
    if local_data_end > len(raw):
        raise ValueError("target compressed data is truncated")
    local_name = raw[local_name_start : local_name_start + local_name_len]
    local_extra = raw[
        local_name_start + local_name_len : local_name_start + local_name_len + local_extra_len
    ]
    central_extra_start = int(target["offset"]) + 46 + int(target["name_len"])
    central_extra = raw[central_extra_start : central_extra_start + int(target["extra_len"])]
    if local_name != target["name_bytes"] or local_extra != central_extra:
        raise ValueError("target local and central name/extra fields differ")
    if local_flag != target["flag"] or local_method != target["method"]:
        raise ValueError("target local and central method/flags differ")
    if local_crc != target["crc"] or local_csize != target["csize"] or local_usize != target["usize"]:
        raise ValueError("target local and central CRC/size fields differ")
    if target["flag"] & 0x08:
        raise ValueError("target uses a data descriptor; fixed-slot surgery is unsafe")
    if target["method"] != zipfile.ZIP_DEFLATED:
        raise ValueError("target executable is not a DEFLATE member")

    target = {
        **target,
        "local_offset": local,
        "local_crc_offset": local + 14,
        "central_crc_offset": int(target["offset"]) + 16,
        "data_start": local_data_start,
        "data_end": local_data_end,
        "local_name_len": local_name_len,
        "local_extra_len": local_extra_len,
        "local_needed": local_needed,
        "local_mtime": local_mtime,
        "local_mdate": local_mdate,
    }
    return {
        "eocd_offset": eocd_offset,
        "eocd": eocd,
        "records": records,
        "target": target,
    }


def raw_deflate(data: bytes, level: int, strategy: int) -> bytes:
    compressor = zlib.compressobj(
        level=level,
        method=zlib.DEFLATED,
        wbits=-15,
        memLevel=8,
        strategy=strategy,
    )
    return compressor.compress(data) + compressor.flush()


def compress_to_fixed_slot(data: bytes, slot_size: int) -> tuple[bytes, int, str]:
    first = raw_deflate(data, 9, zlib.Z_DEFAULT_STRATEGY)
    best = first
    strategy_name = "default"
    if len(best) > slot_size:
        candidates = [
            (zlib.Z_FILTERED, "filtered"),
            (zlib.Z_HUFFMAN_ONLY, "huffman_only"),
            (zlib.Z_RLE, "rle"),
        ]
        for strategy, name in candidates:
            candidate = raw_deflate(data, 9, strategy)
            if len(candidate) < len(best):
                best, strategy_name = candidate, name
    if len(best) > slot_size:
        raise ValueError(
            f"patched executable compresses to {len(best)} bytes, larger than "
            f"the fixed {slot_size}-byte ZIP slot"
        )
    raw_size = len(best)
    return best + (b"\0" * (slot_size - raw_size)), raw_size, strategy_name


def replace_zip_member(raw: bytes, executable: bytes) -> tuple[bytes, dict[str, Any]]:
    layout = parse_zip_layout(raw)
    target = layout["target"]
    if len(executable) != int(target["usize"]):
        raise ValueError(
            f"patched executable size {len(executable)} differs from source "
            f"member size {target['usize']}"
        )
    compressed, raw_compressed_size, strategy = compress_to_fixed_slot(
        executable, int(target["csize"])
    )
    crc = zlib.crc32(executable) & 0xFFFFFFFF
    output = bytearray(raw)
    output[int(target["data_start"]) : int(target["data_end"])] = compressed
    struct.pack_into("<I", output, int(target["local_crc_offset"]), crc)
    struct.pack_into("<I", output, int(target["central_crc_offset"]), crc)
    return bytes(output), {
        "target_member": EXECUTABLE,
        "source_compressed_size": int(target["csize"]),
        "raw_deflate_size": raw_compressed_size,
        "padding_bytes": int(target["csize"]) - raw_compressed_size,
        "compression_strategy": strategy,
        "crc32": f"{crc:08x}",
        "local_crc_offset": int(target["local_crc_offset"]),
        "central_crc_offset": int(target["central_crc_offset"]),
        "data_start": int(target["data_start"]),
        "data_end": int(target["data_end"]),
    }


def outside_ranges_equal(source: bytes, output: bytes, allowed: list[tuple[int, int]]) -> bool:
    if len(source) != len(output):
        return False
    merged: list[list[int]] = []
    for start, end in sorted(allowed):
        if start < 0 or end < start or end > len(source):
            return False
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    cursor = 0
    for start, end in merged:
        if source[cursor:start] != output[cursor:start]:
            return False
        cursor = end
    return source[cursor:] == output[cursor:]


def verify_zip_output(
    source: bytes, output: bytes, expected_executable: bytes, zip_meta: dict[str, Any]
) -> dict[str, Any]:
    layout = parse_zip_layout(source)
    target = layout["target"]
    if not outside_ranges_equal(
        source,
        output,
        [
            (int(target["local_crc_offset"]), int(target["local_crc_offset"]) + 4),
            (int(target["data_start"]), int(target["data_end"])),
            (int(target["central_crc_offset"]), int(target["central_crc_offset"]) + 4),
        ],
    ):
        raise ValueError("raw ZIP bytes changed outside the target member")

    with zipfile.ZipFile(io.BytesIO(source), "r") as source_zip, zipfile.ZipFile(
        io.BytesIO(output), "r"
    ) as output_zip:
        bad_member = output_zip.testzip()
        if bad_member is not None:
            raise ValueError(f"output ZIP CRC check failed for {bad_member}")
        source_names = source_zip.namelist()
        output_names = output_zip.namelist()
        if source_names != output_names:
            raise ValueError("ZIP member order or names changed")
        changed: list[str] = []
        for name in source_names:
            if source_zip.read(name) != output_zip.read(name):
                changed.append(name)
        if changed != [EXECUTABLE]:
            raise ValueError(f"unexpected changed ZIP members: {changed!r}")
        if output_zip.read(EXECUTABLE) != expected_executable:
            raise ValueError("output executable does not match patched bytes")
        source_info = source_zip.getinfo(EXECUTABLE)
        output_info = output_zip.getinfo(EXECUTABLE)
        if (
            output_info.compress_size != source_info.compress_size
            or output_info.file_size != source_info.file_size
            or output_info.CRC != (zlib.crc32(expected_executable) & 0xFFFFFFFF)
        ):
            raise ValueError("target ZIP metadata is inconsistent after patch")

    return {
        "zip_crc": "ok",
        "member_order_and_names_unchanged": True,
        "changed_members": [EXECUTABLE],
        "non_target_members_unchanged": True,
        "raw_non_target_bytes_unchanged": True,
        "archive_size_unchanged": len(source) == len(output),
        "fixed_slot_compression": zip_meta,
    }


def write_exclusive(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(path)
    with path.open("xb") as stream:
        stream.write(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    report_path = args.report.resolve() if args.report else None
    if source.name != EXPECTED_INPUT_NAME:
        raise SystemExit(
            f"refusing input {source.name!r}; expected already-fixed IPA {EXPECTED_INPUT_NAME!r}"
        )
    if source == output:
        raise SystemExit("refusing to overwrite the input IPA")
    if not source.is_file():
        raise SystemExit(f"input IPA does not exist: {source}")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")
    if report_path is not None and report_path.exists():
        raise SystemExit(f"refusing to overwrite existing report: {report_path}")

    source_archive = source.read_bytes()
    with zipfile.ZipFile(io.BytesIO(source_archive), "r") as source_zip:
        original_executable = source_zip.read(EXECUTABLE)
    patched_executable, audit = patch_fat_executable(original_executable)
    patched_fat_verification = verify_patched_fat(patched_executable)
    output_archive, zip_meta = replace_zip_member(source_archive, patched_executable)
    zip_verification = verify_zip_output(
        source_archive, output_archive, patched_executable, zip_meta
    )

    try:
        write_exclusive(output, output_archive)
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite existing output: {output}") from exc

    report = {
        "input": str(source),
        "output": str(output),
        "input_sha256_ipa": sha256(source_archive),
        "output_sha256_ipa": sha256(output_archive),
        "input_sha256_executable": sha256(original_executable),
        "output_sha256_executable": sha256(patched_executable),
        "executable": EXECUTABLE,
        "font_change": {
            "title": "20.0 -> 23.0 (+3)",
            "body": "15.0 -> 18.0 (+3)",
            "button": "18.0 unchanged",
            "implementation": "post-factory CCLabel fontSize_ write followed by original setString:",
            "scope": "invasion unlock, level-up, and zombie-camera alert factories",
        },
        "audit": audit,
        "verification": {
            "fat": patched_fat_verification,
            "zip": zip_verification,
        },
        "code_signature": "invalidated by executable modification; intended for touchHLE",
    }
    if report_path is not None:
        report_bytes = (json.dumps(report, ensure_ascii=True, indent=2) + "\n").encode(
            "utf-8"
        )
        try:
            write_exclusive(report_path, report_bytes)
        except FileExistsError as exc:
            raise SystemExit(f"refusing to overwrite existing report: {report_path}") from exc
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

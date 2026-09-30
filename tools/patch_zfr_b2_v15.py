#!/usr/bin/env python3
"""v15fix - user feedback batch 2, part 1.

Four independent changes on top of v14fix:

#5  Repairs three mojibake values in the Chinese Localizable.strings.

    The codex patch ladder rewrote 金子 -> 金币 across the whole file; three
    entries came out as garbage instead:

        '+%ig'                    '+%i金子'          -> '+%iėĚ'         (now)
        '+%ig (Fertilizer)'       '+%i金子(化肥作用)'  -> '+%iėĚ(ĆđăĐ)'
        '+%ig (Fertilizer Bonus)' '+%i金子(化肥奖励)'  -> '+%iėĚ(ĆđĈą)'

    'ė' (U+0117) and 'Ě' (U+011A) are Latin Extended-A; Arial draws them as a
    dotted e and a caroned E, so "+200金币" renders as "+200eE" - exactly what
    the user photographed.  The originals were recovered from the untouched
    baseline `ZFR 1.0.zh-CN-unsigned.ipa`; every replacement has the SAME number
    of UTF-16 code units, so this is a byte-for-byte in-place edit inside the
    binary plist and the IPA size does not change.

#1  "已使用Invasion Voucher!"  - the %@ argument is not localised.
#3  "Insta-Grow (6)" where it should read "瞬间成熟 (6)" - same cause.

    Both are fixed by routing the stringWithFormat: argument through the
    zfrLocFormat stub v13fix installed:

        r3 = zfrLoc(r3) = [[NSBundle mainBundle]
                              localizedStringForKey:r3 value:r3 table:nil]

    v13fix's stub took the name from a hardcoded register (r5 in sub6, r4 in
    sub9).  Every call site - the two original ones and all four new ones -
    already has the name in r3, so the stub is generalised to `mov r0, r3`.

Sites (sub6 = ARM, sub9 = Thumb):
    #1  ZFMarketMenu  -alertWindow:dismissedPositive:   0x7389c
    #3  ZFToolManager -onTileClickUp:forTool:           0x3371c, 0x33a34
        ZFToolManager -onTileClickUp:forTool:  (sub9)   0x26d90

Everything is width preserving; both slices are patched because it is still
unknown which slice touchHLE executes.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_zfr_alert_fonts import (  # noqa: E402
    EXECUTABLE, compress_to_fixed_slot, fat_descriptors, outside_ranges_equal,
    parse_zip_layout, replace_zip_member, sha256, write_exclusive,
)
from patch_zfr_ability_v13 import arm_bl, thumb_branch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "zombie_farm_ipa"
BASE = "Zombie Farm ZFR 1.0.zh-CN-complete-final"
INPUT_NAME = f"{BASE}.fixed-fonts-v14fix.ipa"
OUTPUT_NAME = f"{BASE}.fixed-fonts-v15fix.ipa"
REPORT_NAME = f"{BASE}.fixed-fonts-v15fix.report.json"

STUB_SUB6 = 0x16D594
STUB_SUB9 = 0x10C470
OBJC_MSGSEND_SUB6 = 0x393FE0
OBJC_MSGSEND_SUB9 = 0x2D014C

FORBIDDEN_PRIOR: dict[int, list[tuple[int, int]]] = {
    6: [(0x1B464, 0x1B810),      # codex helper network
        (0x16A5F8, 0x16A70C),    # v12fix stopListening
        (0x16D594, 0x16D5AC)],   # v13fix stub (this patch edits 1 word inside)
    9: [(0x14F6C, 0x151C0),
        (0x10A1DC, 0x10A29C),
        (0x10C470, 0x10C486)],
}
# the two words this patch is allowed to touch inside the v13 stubs
STUB_EDIT = {(6, 0x16D598), (9, 0x10C472)}

# (addr, expected original bytes, note)
RETARGETS: dict[int, list[tuple[int, str, str]]] = {
    6: [
        (0x7389C, "cf810ceb", "#1 ZFMarketMenu alertWindow:dismissedPositive: -> stub"),
        (0x3371C, "2f820deb", "#3 ZFToolManager onTileClickUp:forTool: -> stub"),
        (0x33A34, "69810deb", "#3 ZFToolManager onTileClickUp:forTool: (2nd) -> stub"),
    ],
    9: [
        (0x26D90, "a9f2dce9", "#3 ZFToolManager onTileClickUp:forTool: -> stub"),
    ],
}

# ---------------------------------------------------------------- strings
LANG_MEMBER = "Payload/ZFR.app/%s.lproj/Localizable.strings"
# longest first: the shorter string is a prefix of the longer ones
REPAIRS = {
    "zh-Hans": [
        ("+%iėĚ(ĆđĈą)", "+%i金币(化肥奖励)"),
        ("+%iėĚ(ĆđăĐ)", "+%i金币(化肥作用)"),
        ("+%iėĚ", "+%i金币"),
    ],
    "zh-Hant": [
        ("+%iėĚ(ĆđĈą)", "+%i金币(化肥獎勵)"),
        ("+%iėĚ(ĆđăĐ)", "+%i金币(化肥作用)"),
        ("+%iėĚ", "+%i金币"),
    ],
}


def replace_named_member(raw: bytes, name: str, data: bytes) -> tuple[bytes, dict[str, Any]]:
    """Same fixed-slot surgery as replace_zip_member, but for an arbitrary member."""
    layout = parse_zip_layout(raw)
    record = None
    for r in layout["records"]:
        if r["name"] == name:
            record = r
            break
    if record is None:
        raise ValueError("ZIP member %r not found" % name)
    if record["method"] != zipfile.ZIP_DEFLATED:
        raise ValueError("%s is not DEFLATE" % name)
    if record["flag"] & 0x08:
        raise ValueError("%s uses a data descriptor" % name)
    if len(data) != int(record["usize"]):
        raise ValueError("%s: new size %d != original %d" % (name, len(data), record["usize"]))

    local = int(record["local_offset"])
    if raw[local:local + 4] != b"PK\x03\x04":
        raise ValueError("%s local header malformed" % name)
    (_sig, _need, _flag, _method, _mt, _md, local_crc, local_csize, local_usize,
     name_len, extra_len) = struct.unpack_from("<I5H3I2H", raw, local)
    if local_crc != record["crc"] or local_csize != record["csize"] or \
            local_usize != record["usize"]:
        raise ValueError("%s local/central size mismatch" % name)
    data_start = local + 30 + name_len + extra_len
    data_end = data_start + int(record["csize"])

    compressed, raw_size, strategy = compress_to_fixed_slot(data, int(record["csize"]))
    crc = zlib.crc32(data) & 0xFFFFFFFF
    out = bytearray(raw)
    out[data_start:data_end] = compressed
    struct.pack_into("<I", out, local + 14, crc)
    struct.pack_into("<I", out, int(record["offset"]) + 16, crc)
    return bytes(out), {
        "member": name,
        "usize": len(data),
        "slot": int(record["csize"]),
        "raw_deflate_size": raw_size,
        "padding_bytes": int(record["csize"]) - raw_size,
        "compression_strategy": strategy,
        "crc32": f"{crc:08x}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT / INPUT_NAME)
    ap.add_argument("--output", type=Path, default=ROOT / OUTPUT_NAME)
    ap.add_argument("--report", type=Path, default=ROOT / REPORT_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from audit_zfr_ipa import parse_fat

    source = args.input.read_bytes()
    with zipfile.ZipFile(args.input) as archive:
        original = archive.read(EXECUTABLE)
        members = {n: archive.read(n) for n in archive.namelist() if n.endswith("Localizable.strings")}

    descriptors = {d["subtype"]: d for d in fat_descriptors(original)}
    slices = {sl.subtype: sl for sl in parse_fat(original)}
    if set(slices) != {6, 9}:
        raise ValueError("unexpected FAT slice set")

    # ---- 1. generalise the v13 stub: mov r0, rX -> mov r0, r3
    out = bytearray(original)
    applied: list[dict[str, Any]] = []

    def write(subtype, addr, old, new, note, allow_stub=False):
        if len(old) != len(new):
            raise ValueError("width change at %#x" % addr)
        if not allow_stub:
            for lo, hi in FORBIDDEN_PRIOR.get(subtype, []):
                if addr < hi and lo < addr + len(new):
                    raise ValueError("sub%d %#x overlaps forbidden %#x" % (subtype, addr, lo))
        absolute = descriptors[subtype]["offset"] + slices[subtype].addr_to_file(addr)
        found = bytes(out[absolute:absolute + len(old)])
        if found != old:
            raise ValueError("sub%d %#x: expected %s, found %s"
                             % (subtype, addr, old.hex(), found.hex()))
        out[absolute:absolute + len(new)] = new
        applied.append({"subtype": subtype, "addr": f"{addr:#08x}", "file_offset": absolute,
                        "len": len(new), "old_prefix": old.hex(), "new_prefix": new.hex(),
                        "note": note})

    write(6, 0x16D598, bytes.fromhex("0500a0e1"), bytes.fromhex("0300a0e1"),
          "stub: mov r0, r5 -> mov r0, r3 (generalised)", allow_stub=True)
    write(9, 0x10C472, bytes.fromhex("2046"), bytes.fromhex("1846"),
          "stub: mov r0, r4 -> mov r0, r3 (generalised)", allow_stub=True)

    # ---- 2. retarget the four new stringWithFormat: calls
    for subtype, sites in RETARGETS.items():
        stub = STUB_SUB6 if subtype == 6 else STUB_SUB9
        patched = []
        for addr, old_hex, note in sites:
            raw = (arm_bl(addr, stub) if subtype == 6
                   else thumb_branch(addr, stub, False))
            write(subtype, addr, bytes.fromhex(old_hex), raw, note)
            patched.append((addr, raw))
        # decode-back check
        from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM if subtype == 6 else CS_MODE_THUMB)
        md.detail = True
        for addr, raw in patched:
            ins = list(md.disasm(raw, addr))
            if len(ins) != 1 or ins[0].mnemonic != "bl" or \
                    int(ins[0].op_str.lstrip("#"), 0) != stub:
                raise ValueError("sub%d %#x did not decode back to the stub" % (subtype, addr))

    if len(out) != len(original):
        raise ValueError("patched executable changed size")
    exe_patched = bytes(out)
    allowed = sorted((s["file_offset"], s["file_offset"] + s["len"]) for s in applied)
    if not outside_ranges_equal(original, exe_patched, [list(r) for r in allowed]):
        raise ValueError("executable differs outside the intended ranges")

    # ---- 3. repair the localisation values
    ipa_patched, exe_meta = replace_zip_member(source, exe_patched)
    zip_meta: dict[str, Any] = {"executable": exe_meta}
    for lang, pairs in REPAIRS.items():
        name = LANG_MEMBER % lang
        raw = members[name]
        new_raw = raw
        detail = []
        for old, new in pairs:
            if len(old) != len(new):
                raise ValueError("%s: %r -> %r changes length" % (lang, old, new))
            ob = old.encode("utf-16-be")
            nb = new.encode("utf-16-be")
            count = new_raw.count(ob)
            if count != 1:
                raise ValueError("%s: %r occurs %d times" % (lang, old, count))
            new_raw = new_raw.replace(ob, nb)
            detail.append({"from": old, "to": new, "utf16be_offset": raw.find(ob)})
        # re-parse and confirm
        import plistlib
        table = plistlib.loads(new_raw)
        for _old, new in pairs:
            hit = [k for k, v in table.items() if v == new]
            if not hit and new.count("%") == 0:
                raise ValueError("%s: repaired value %r not found after parse" % (lang, new))
        if len(new_raw) != len(raw):
            raise ValueError("%s: member size changed" % lang)
        ipa_patched, meta = replace_named_member(ipa_patched, name, new_raw)
        meta["repairs"] = detail
        zip_meta[lang] = meta
        members[name] = new_raw

    if len(ipa_patched) != len(source):
        raise ValueError("output archive changed size")
    with zipfile.ZipFile(io.BytesIO(ipa_patched)) as archive:
        if archive.read(EXECUTABLE) != exe_patched:
            raise ValueError("executable round-trip failed")
        if archive.testzip() is not None:
            raise ValueError("output archive failed testzip()")
        for lang in REPAIRS:
            n = LANG_MEMBER % lang
            if archive.read(n) != members[n]:
                raise ValueError("%s round-trip failed" % n)

    report: dict[str, Any] = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": Path(__file__).name,
        "kind": "FIX",
        "batches": {
            "#5": "repair three mojibake values in zh-Hans/zh-Hant Localizable.strings "
                  "(金子->金币 replacements that the codex patch ladder corrupted)",
            "#1": "%@ Used! - route the item name through zfrLocFont",
            "#3": "%@ (%i) - route the item name through zfrLocFont",
        },
        "input": {"name": args.input.name, "size": len(source),
                  "sha256": sha256(source), "executable_sha256": sha256(original)},
        "sites": applied,
        "site_count": len(applied),
        "localization": zip_meta,
        "forbidden_regions": {str(k): [[f"{lo:#x}", f"{hi:#x}"] for lo, hi in v]
                              for k, v in FORBIDDEN_PRIOR.items()},
    }

    if args.dry_run:
        report["dry_run"] = True
        print(json.dumps(report, indent=2))
        return 0

    write_exclusive(args.output, ipa_patched)
    report["output"] = {"name": args.output.name, "size": len(ipa_patched),
                        "sha256": sha256(ipa_patched), "executable_sha256": sha256(exe_patched)}
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("wrote %s  (%d bytes)" % (args.output.name, len(ipa_patched)))
    print("  ipa sha256 = %s" % report["output"]["sha256"])
    for s in applied:
        print("  sub%d %s +%d  %s" % (s["subtype"], s["addr"], s["len"], s["note"]))
    for lang, meta in zip_meta.items():
        if lang == "executable":
            continue
        print("  %s: %d repair(s)  slot %d, deflate %d, pad %d"
              % (lang, len(meta["repairs"]), meta["slot"], meta["raw_deflate_size"],
                 meta["padding_bytes"]))
    print("report: %s" % args.report.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

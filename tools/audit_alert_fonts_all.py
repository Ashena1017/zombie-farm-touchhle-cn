#!/usr/bin/env python3
"""Static audit of title/body label font sizes in all ZFAlertWindow code.

This is intentionally read-only.  It supplements audit_zfr_ipa.Slice with the
ZFAlertWindow metaclass method list, which the generic parser does not expose
for this binary, and uses the combined method starts to keep class/instance
method ranges separate.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm_const import (
    ARM_OP_IMM,
    ARM_OP_MEM,
    ARM_OP_REG,
    ARM_REG_PC,
    ARM_REG_R0,
    ARM_REG_R1,
    ARM_REG_R2,
    ARM_REG_R3,
    ARM_REG_R4,
    ARM_REG_R5,
    ARM_REG_R6,
    ARM_REG_R7,
    ARM_REG_R8,
    ARM_REG_R9,
    ARM_REG_R10,
    ARM_REG_R11,
    ARM_REG_R12,
    ARM_REG_SP,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_zfr_ipa import Method, parse_fat  # noqa: E402


EXECUTABLE = "Payload/ZFR.app/ZFR"
OBJC_MSG_SEND = {6: 0x393FE0, 9: 0x2D014C}
ZF_CLASS_ADDR = {6: 0x45F430, 9: 0x39B3B8}

TARGET_SELECTORS = {
    "labelWithString:dimensions:alignment:fontName:fontSize:",
    "labelWithString:fontName:fontSize:",
    "setFontSize:",
    "setString:",
    "setTitle1:",
    "setBody1:",
    "setBody2:",
    "title1",
    "body1",
    "body2",
}

REGS = (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R4,
        ARM_REG_R5, ARM_REG_R6, ARM_REG_R7, ARM_REG_R8, ARM_REG_R9,
        ARM_REG_R10, ARM_REG_R11, ARM_REG_R12)


@dataclass
class Call:
    address: int
    selector: str | None
    args: dict[int, int | None]
    stack: dict[int, int | None]
    target: int | None
    size_float: float | None
    size_raw: int | None


def u32(sl, address: int) -> int | None:
    off = sl.addr_to_file(address)
    if off is None or off + 4 > len(sl.data):
        return None
    return struct.unpack_from("<I", sl.data, off)[0]


def pc_base(address: int, thumb: bool) -> int:
    base = address + (4 if thumb else 8)
    return base & ~3 if thumb else base


def cstr(sl, address: int | None) -> str | None:
    if address is None:
        return None
    return sl.cstr(address) if not sl.cstr(address).startswith("<addr ") else None


def resolve_selector(sl, value: int | None) -> str | None:
    if value is None:
        return None
    text = cstr(sl, value)
    if text:
        return text
    pointed = u32(sl, value)
    return cstr(sl, pointed)


def float_value(raw: int | None) -> float | None:
    if raw is None:
        return None
    return struct.unpack("<f", struct.pack("<I", raw & 0xFFFFFFFF))[0]


def get_value(op, regs: dict[int, int | None]) -> int | None:
    if op.type == ARM_OP_IMM:
        return op.imm
    if op.type == ARM_OP_REG:
        return regs.get(op.reg)
    return None


def add_method_list(sl, class_addr: int) -> list[Method]:
    """Read the ZFAlertWindow metaclass methods absent from sl.methods."""
    meta = u32(sl, class_addr)
    if meta is None:
        raise ValueError(f"cannot read ZFAlertWindow isa at {class_addr:#x}")
    ro = u32(sl, meta + 16)
    if ro is None:
        raise ValueError(f"cannot read metaclass data at {meta:#x}")
    list_addr = u32(sl, ro + 20)
    if list_addr is None:
        raise ValueError("missing ZFAlertWindow metaclass method list")
    off = sl.addr_to_file(list_addr)
    if off is None:
        raise ValueError(f"metaclass method list {list_addr:#x} not mapped")
    entsize, count = struct.unpack_from("<II", sl.data, off)
    out: list[Method] = []
    for index in range(count):
        entry = off + 8 + index * entsize
        name_ptr, types_ptr, imp = struct.unpack_from("<III", sl.data, entry)
        out.append(Method(
            "ZFAlertWindow", "class", sl.cstr(name_ptr), sl.cstr(types_ptr),
            imp, sl.addr_to_file(imp),
        ))
    return out


def method_ranges(sl):
    methods = [m for m in sl.methods if m.file_offset is not None]
    methods += add_method_list(sl, ZF_CLASS_ADDR[sl.subtype])
    starts = sorted({m.imp & ~1 for m in methods if m.file_offset is not None})
    ranges = []
    for method in methods:
        start = method.imp & ~1
        end = next((candidate for candidate in starts if candidate > start), None)
        ranges.append((method, start, end))
    return ranges


def disassemble_calls(sl, code: bytes, start: int, thumb: bool) -> list[Call]:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.detail = True
    regs: dict[int, int | None] = {}
    stack: dict[int, int | None] = {}
    calls: list[Call] = []
    msg_send = OBJC_MSG_SEND[sl.subtype]

    for ins in md.disasm(code, start):
        ops = ins.operands
        if ins.mnemonic in {"mov", "movs"} and len(ops) == 2 and ops[0].type == ARM_OP_REG:
            regs[ops[0].reg] = get_value(ops[1], regs)
        elif ins.mnemonic == "movw" and len(ops) == 2 and ops[0].type == ARM_OP_REG:
            regs[ops[0].reg] = ops[1].imm
        elif ins.mnemonic == "movt" and len(ops) == 2 and ops[0].type == ARM_OP_REG:
            regs[ops[0].reg] = ((regs.get(ops[0].reg) or 0) & 0xFFFF) | (ops[1].imm << 16)
        elif ins.mnemonic in {"add", "adds"} and len(ops) in {2, 3} and ops[0].type == ARM_OP_REG:
            if len(ops) == 2:
                left = regs.get(ops[0].reg)
                if ops[1].type == ARM_OP_REG and ops[1].reg == ARM_REG_PC:
                    right = ins.address + (4 if thumb else 8)
                else:
                    right = get_value(ops[1], regs)
            else:
                left = get_value(ops[1], regs)
                right = (pc_base(ins.address, thumb)
                         if ops[2].type == ARM_OP_REG and ops[2].reg == ARM_REG_PC
                         else get_value(ops[2], regs))
            regs[ops[0].reg] = left + right if left is not None and right is not None else None
        elif ins.mnemonic in {"orr", "orrs"} and len(ops) == 3 and ops[0].type == ARM_OP_REG:
            left, right = get_value(ops[1], regs), get_value(ops[2], regs)
            regs[ops[0].reg] = left | right if left is not None and right is not None else None
        elif ins.mnemonic == "ldr" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mem = ops[1].mem
            if mem.base == ARM_REG_PC:
                address = pc_base(ins.address, thumb) + mem.disp
                if mem.index:
                    index = regs.get(mem.index)
                    address = address + index if index is not None else None
            else:
                base = regs.get(mem.base)
                index = regs.get(mem.index, 0) if mem.index else 0
                address = base + mem.disp + index if base is not None and index is not None else None
            regs[ops[0].reg] = u32(sl, address) if address is not None else None
        elif ins.mnemonic == "str" and len(ops) == 2 and ops[0].type == ARM_OP_REG and ops[1].type == ARM_OP_MEM:
            mem = ops[1].mem
            if mem.base == ARM_REG_SP and not mem.index:
                stack[mem.disp] = regs.get(ops[0].reg)
        elif ins.mnemonic in {"stm", "stmia", "stmib"} and len(ops) >= 2:
            # The compiler uses STM to place contiguous outgoing arguments.
            mem, reglist = ops[0], ops[1]
            if mem.type == ARM_OP_MEM and mem.base == ARM_REG_SP:
                # Capstone exposes the register list as a REG operand list in
                # some versions; fall back to the textual form when needed.
                pass

        if ins.mnemonic in {"bl", "blx"}:
            target = ops[0].imm if ops and ops[0].type == ARM_OP_IMM else None
            if target == msg_send:
                selector = resolve_selector(sl, regs.get(ARM_REG_R1))
                args = {i: regs.get(reg) for i, reg in enumerate((ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3))}
                # For the common labelWithString dimensions form, the final
                # float is the fourth outgoing word at sp+0xc.
                raw = None
                if selector == "labelWithString:dimensions:alignment:fontName:fontSize:":
                    raw = stack.get(0x0C)
                elif selector == "labelWithString:fontName:fontSize:":
                    raw = stack.get(0x00, args.get(3))
                elif selector == "setFontSize:":
                    raw = args.get(2)
                calls.append(Call(ins.address, selector, args, dict(stack), target, float_value(raw), raw))
            for reg in (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_R12):
                regs[reg] = None
    return calls


def relevant_method(method: Method) -> bool:
    return method.cls.startswith("ZFAlertWindow")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ipa", type=Path)
    args = ap.parse_args()
    with zipfile.ZipFile(args.ipa) as zf:
        fat = zf.read(EXECUTABLE)
    for slice_index, sl in enumerate(parse_fat(fat)):
        thumb = sl.subtype == 9
        print(f"===== slice {slice_index} subtype={sl.subtype} =====")
        for method, start, end in sorted(method_ranges(sl), key=lambda item: item[1]):
            if not relevant_method(method):
                continue
            off = sl.addr_to_file(start)
            if off is None:
                continue
            limit = (end - start) if end is not None else 4096
            code = sl.data[off : off + min(limit, 0x4000)]
            calls = [call for call in disassemble_calls(sl, code, start, thumb)
                     if call.selector in TARGET_SELECTORS]
            if not calls:
                continue
            print(f"\n-- {method.cls} [{method.kind}] {method.selector} imp={method.imp:#x} range={start:#x}-{end and hex(end) or '-'}")
            for call in calls:
                size = ""
                if call.size_raw is not None:
                    size = f" size={call.size_float!r} raw={call.size_raw:#x}"
                args_text = ",".join(f"r{k}={v!r}" for k, v in call.args.items())
                stack_text = ",".join(f"sp+{k:#x}={v!r}" for k, v in sorted(call.stack.items()) if v is not None)
                print(f"  call={call.address:#x} selector={call.selector!r}{size} args[{args_text}] stack[{stack_text}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Check 16 KiB load segment alignment in every ARM64 shared library of an APK."""
from pathlib import Path
import struct
import sys
from zipfile import ZipFile


def verify(apk):
    with ZipFile(apk) as archive:
        libs = [entry for entry in archive.infolist()
                if entry.filename.startswith("lib/arm64-v8a/") and entry.filename.endswith(".so")]
        if not libs:
            raise ValueError("APK has no ARM64 libraries")
        for entry in libs:
            with archive.open(entry) as stream:
                header = stream.read(64)
                if len(header) != 64 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != 183:
                    raise ValueError(f"{entry.filename}: expected little-endian AArch64 ELF64")
                offset = struct.unpack_from("<Q", header, 32)[0]
                stride, count = struct.unpack_from("<HH", header, 54)
                if stride < 56 or offset + stride * count > entry.file_size:
                    raise ValueError(f"{entry.filename}: invalid program header table")
                stream.seek(offset)
                loads = 0
                for _ in range(count):
                    kind, _, file_offset, address, _, _, _, alignment = struct.unpack_from("<II6Q", stream.read(stride))
                    if kind == 1:
                        if alignment < 16384 or alignment & (alignment - 1) or (address - file_offset) % 16384:
                            raise ValueError(f"{entry.filename}: PT_LOAD at {file_offset:#x} has alignment {alignment}")
                        loads += 1
                if not loads:
                    raise ValueError(f"{entry.filename}: missing PT_LOAD")
                print(f"{entry.filename}: {loads} load segments support 16 KiB pages")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))

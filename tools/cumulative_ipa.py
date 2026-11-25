"""Rebuild the release IPA from the original unsigned IPA (Python 3.14+)."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from compression import zstd
from copy import copy
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


IPA_DIR = Path(__file__).resolve().parents[1] / "zombie_farm_ipa"
RELEASE = json.loads((IPA_DIR.parent / "release.json").read_text(encoding="utf-8"))
CUMULATIVE = RELEASE["cumulativePatch"]
BASE = IPA_DIR / CUMULATIVE["baseName"]
TARGET = IPA_DIR / RELEASE["ipa"]["name"]
PATCH = IPA_DIR / CUMULATIVE["name"]
BASE_SHA256 = CUMULATIVE["baseSha256"]
TARGET_SHA256 = RELEASE["ipa"]["sha256"]
STORED_TARGET_SIZE = CUMULATIVE["storedTargetSize"]
STORED_TARGET_SHA256 = CUMULATIVE["storedTargetSha256"]


def verify(data, expected_hash, label):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_hash:
        raise ValueError(f"{label}: expected SHA-256 {expected_hash}, got {actual}")


def repack(data, method):
    # Removing DEFLATE before diffing preserves matches between members that
    # were recompressed in later IPAs. Only directory entries use ZIP_STORED in v30.
    result = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(result, "w") as dest:
        dest.comment = source.comment
        for entry in source.infolist():
            dest.writestr(copy(entry), source.read(entry),
                          compress_type=ZIP_STORED if entry.is_dir() else method,
                          compresslevel=6 if method == ZIP_DEFLATED and not entry.is_dir() else None)
    return result.getvalue()


def publish(path, data):
    # Publish a fully verified file without overwriting a concurrent writer.
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        candidate = Path(temp) / "candidate"
        candidate.write_bytes(data)
        try:
            if os.name == "nt":
                candidate.rename(path)
            else:
                os.link(candidate, path)
        except FileExistsError:
            with path.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").digest() != hashlib.sha256(data).digest():
                    raise ValueError(f"existing file differs, choose another output: {path}") from None


def restore(patch, prefix):
    if zstd.get_frame_info(patch).decompressed_size != STORED_TARGET_SIZE:
        raise ValueError("unexpected cumulative patch frame size")
    decoder = zstd.ZstdDecompressor(
        zstd_dict=prefix, options={zstd.DecompressionParameter.window_log_max: 27}
    )
    stored = decoder.decompress(patch, max_length=STORED_TARGET_SIZE + 1)
    if not decoder.eof or decoder.unused_data or len(stored) != STORED_TARGET_SIZE:
        raise ValueError("incomplete cumulative patch or trailing data")
    verify(stored, STORED_TARGET_SHA256, "reconstructed ZIP entries")
    ipa = repack(stored, ZIP_DEFLATED)
    verify(ipa, TARGET_SHA256, "reconstructed IPA")
    return ipa


def run(args):
    source = args.base.read_bytes()
    verify(source, BASE_SHA256, "original IPA")
    prefix = zstd.ZstdDict(repack(source, ZIP_STORED), is_raw=True).as_prefix
    del source
    if args.command == "create":
        target = args.target.read_bytes()
        verify(target, TARGET_SHA256, "target IPA")
        stored = repack(target, ZIP_STORED)
        del target
        verify(stored, STORED_TARGET_SHA256, "target ZIP entries")
        options = zstd.CompressionParameter
        result = zstd.compress(stored, zstd_dict=prefix, options={
            options.compression_level: 12,
            options.window_log: 27,
            options.enable_long_distance_matching: 1,
            options.checksum_flag: 1,
        })
        del stored
        restore(result, prefix)
    else:
        result = restore(args.patch.read_bytes(), prefix)
    publish(args.output, result)
    print(f"{args.output}  {len(result):,} bytes  SHA-256 {hashlib.sha256(result).hexdigest()}")


def main():
    # Redirected Windows output can use a code page without the bundled filename's characters.
    sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply", help="reconstruct and verify the release IPA")
    apply.add_argument("--base", type=Path, default=BASE)
    apply.add_argument("--patch", type=Path, default=PATCH)
    apply.add_argument("--output", type=Path, default=TARGET)
    create = commands.add_parser("create", help="regenerate and verify the cumulative patch")
    create.add_argument("--base", type=Path, default=BASE)
    create.add_argument("--target", type=Path, default=TARGET)
    create.add_argument("--output", type=Path, default=PATCH)
    try:
        run(parser.parse_args())
    except (OSError, ValueError, zstd.ZstdError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()

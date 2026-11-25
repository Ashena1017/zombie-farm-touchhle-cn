"""Restore the Windows and Android native build inputs (Python 3.12+, Git)."""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENDOR = ROOT / "touchHLE/touchHLE-fork/vendor"
GIT_PINS = {
    "stb": ("nothings/stb", "c39c7023ebb833ce099750fe35509aca5662695e"),
    "dynarmic": ("touchHLE/dynarmic", "a41c380246d3d9f9874f0f792d234dc0cc17c180"),
    "openal-soft": ("kcat/openal-soft", "c89b8cf7bba4822f230c69f0a6696a52e5322dca"),
    "SDL": ("libsdl-org/SDL", "07d0f51fa292895443f563f0cbde4cb3802d87fa"),
}
BOOST_NAME = "boost_1_81_0"
BOOST_URL = f"https://archives.boost.io/release/1.81.0/source/{BOOST_NAME}.tar.gz"
BOOST_SHA256 = "205666dea9f6a7cfed87c7a6dfbeb52a2c1b9de55712c9c1a87735d7181452b6"
PVR_BASE = ("https://raw.githubusercontent.com/touchHLE/touchHLE/"
            "fa3d09511d471f505e41abed7c535e4dfbd7c59c/vendor/PVRTDecompress")
PVR_FILES = {
    "LICENSE.md": "b1aea79afab593649ede742eccbb7feb74d216d52d120b99c4d349133871ba9f",
    "PVRTDecompress.cpp": "74559c5a4b8161aafce1ebe984bf8060896feaa81276b614491dbee755d6e4c7",
    "PVRTDecompress.h": "67123a36b99df380af76a65f3dfa3a7f368a153f5401b36a9ff1ed233cee6f5f",
    "README.md": "d9596b56bfa4d30ce97c6757ca5e0a7ef543cadf582b66eb8bfd95d0211125a3",
}


def download(url, dest):
    with urllib.request.urlopen(url, timeout=90) as source, dest.open("xb") as out:
        shutil.copyfileobj(source, out)


def verify(path, expected):
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != expected:
            raise ValueError(f"unexpected SHA-256 for {path}")


def restore_git(vendor):
    for name, (repo, commit) in GIT_PINS.items():
        print(f"{name}: {commit}", flush=True)
        git = ["git", "-C", str(vendor / name)]
        subprocess.run(["git", "init", "--quiet", str(vendor / name)], check=True)
        subprocess.run([*git, "remote", "add", "origin", f"https://github.com/{repo}.git"], check=True)
        subprocess.run([*git, "fetch", "--quiet", "--depth=1", "origin", commit], check=True)
        subprocess.run([*git, "-c", "core.autocrlf=false", "switch", "--quiet", "--detach", commit], check=True)


def restore_boost(vendor, archive):
    # Dynarmic consumes the Boost headers. Omit examples, documentation and tools.
    verify(archive, BOOST_SHA256)
    with tarfile.open(archive, "r|gz") as source:
        for entry in source:
            if entry.name.startswith(f"{BOOST_NAME}/boost/") or entry.name == f"{BOOST_NAME}/LICENSE_1_0.txt":
                source.extract(entry, vendor, filter="data")
    (vendor / BOOST_NAME).rename(vendor / "boost")


def restore(destination, boost_archive):
    if destination.is_symlink() or destination.is_junction():
        raise ValueError(f"destination is a link: {destination}")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError(f"choose an empty or missing vendor directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".vendor-") as stage:
        vendor = Path(stage) / "vendor"
        vendor.mkdir()
        restore_git(vendor)
        print("Boost: 1.81.0", flush=True)
        if boost_archive is None:
            boost_archive = Path(stage) / (BOOST_NAME + ".tar.gz")
            download(BOOST_URL, boost_archive)
        restore_boost(vendor, boost_archive)
        print("PVRTDecompress: sources and license", flush=True)
        pvr = vendor / "PVRTDecompress"
        pvr.mkdir()
        for name, digest in PVR_FILES.items():
            download(f"{PVR_BASE}/{name}", pvr / name)
            verify(pvr / name, digest)
        if destination.exists():
            destination.rmdir()
        vendor.rename(destination)
    print(f"Restored native build inputs: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, default=DEFAULT_VENDOR,
                        help="empty or missing destination (default: the fork's vendor directory)")
    parser.add_argument("--boost-archive", type=Path, help="use an existing boost_1_81_0.tar.gz")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.exit(1, "error: Python 3.12 or newer is required\n")
    try:
        restore(args.vendor.absolute(), args.boost_archive)
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()

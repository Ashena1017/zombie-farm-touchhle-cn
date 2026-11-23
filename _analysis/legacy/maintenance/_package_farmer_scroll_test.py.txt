"""Package and read back the local test builds; never include live data."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '_analysis/dumps/farmer-scroll-20261117'
NAME = 'zombie-farm-windows-x64-v13-farmers-scroll-test'


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def main():
    release = ROOT / 'Release'
    files = sorted(p for p in release.rglob('*') if p.is_file())
    assert len(files) == 45, len(files)
    assert not any((release / 'touchHLE/touchHLE_sandbox').rglob('*'))
    expected = {}
    for line in (release / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        expected[name.replace('\\', '/')] = digest.upper()
    assert len(expected) == 44
    for path in files:
        name = path.relative_to(release).as_posix()
        assert not any(token in name.lower() for token in ('savegame', 'zfr_last', '.log', 'profile.txt'))
        if name != 'SHA256SUMS.txt':
            assert sha(path.read_bytes()) == expected[name], name
    assert (release / 'GameManager.ps1').read_bytes() == (ROOT / 'GameManager.ps1').read_bytes()
    assert (release / 'touchHLE/touchHLE.exe').read_bytes() == (ROOT / 'touchHLE/touchHLE.exe').read_bytes()
    archive = OUT / f'{NAME}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files:
            z.write(path, f'{NAME}/{path.relative_to(release).as_posix()}')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(files)
        for path in files:
            assert z.read(f'{NAME}/{path.relative_to(release).as_posix()}') == path.read_bytes()
    apk = OUT / 'zombie-farm-android-arm64-v13-farmers-scroll-test.apk'
    shutil.copyfile(ROOT / 'touchHLE-zombiefarm-android-arm64/touchHLE-zombiefarm-android-arm64-fixed.apk', apk)
    records = [{'file': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())} for p in (archive, apk)]
    records.append({'file': str(ROOT / 'touchHLE/touchHLE.exe'),
                    'bytes': (ROOT / 'touchHLE/touchHLE.exe').stat().st_size,
                    'sha256': sha((ROOT / 'touchHLE/touchHLE.exe').read_bytes())})
    (OUT / 'test-builds.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps(records, indent=2))
    print('PASS: Windows ZIP 45 files, CRC/full-byte readback, 44 hashes, empty sandbox; APK copy identical')


if __name__ == '__main__':
    main()

param(
    [string]$ApkPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'touchHLE-zombiefarm-android-arm64\touchHLE-zombiefarm-android-arm64-fixed.apk')
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$ipaPath = Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
$expectedOptions = 'com.playforge.ZombieFarm.ZFR: --landscape-right --fps-limit=60 --device-family=iphone --non-blocking-zero-timeout-run-loop'
$expectedLibcxxBytes = 1794776
$expectedLibcxxSha256 = 'F9992C4BA6B7C5A716E3A202FCEB1CE029D6A2B0605838AC6B3219F489DD7970'

if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) { throw "APK not found: $ApkPath" }
if (-not (Test-Path -LiteralPath $ipaPath -PathType Leaf)) { throw "Bundled IPA not found: $ipaPath" }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $ApkPath))
try {
    $ipaEntry = $archive.GetEntry('assets/Zombie_Farm_v29fix.ipa')
    $optionsEntry = $archive.GetEntry('assets/touchHLE_zombiefarm_options.txt')
    $hashEntry = $archive.GetEntry('assets/touchHLE_zombiefarm_ipa.sha256')
    $nativeEntry = $archive.GetEntry('lib/arm64-v8a/libtouchHLE.so')
    $libcxxEntry = $archive.GetEntry('lib/arm64-v8a/libc++_shared.so')
    foreach ($pair in @(
        @{ Name = 'bundled IPA'; Entry = $ipaEntry },
        @{ Name = 'default options'; Entry = $optionsEntry },
        @{ Name = 'IPA hash'; Entry = $hashEntry },
        @{ Name = 'arm64 touchHLE library'; Entry = $nativeEntry },
        @{ Name = 'arm64 libc++ shared library'; Entry = $libcxxEntry }
    )) {
        if ($null -eq $pair.Entry) { throw "APK is missing $($pair.Name)." }
    }

    $ipaStream = $ipaEntry.Open()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $packagedHash = ([BitConverter]::ToString($sha.ComputeHash($ipaStream))).Replace('-', '') }
    finally { $ipaStream.Dispose(); $sha.Dispose() }
    $sourceHash = (Get-FileHash -LiteralPath $ipaPath -Algorithm SHA256).Hash
    if ($packagedHash -ne $sourceHash) { throw 'The APK IPA does not match the repository v29fix IPA.' }
    $hashStream = $hashEntry.Open()
    $hashReader = [IO.StreamReader]::new($hashStream, [Text.Encoding]::ASCII)
    try { $declaredHash = $hashReader.ReadToEnd().Trim() }
    finally { $hashReader.Dispose(); $hashStream.Dispose() }
    if ($declaredHash -ne $sourceHash.ToLowerInvariant()) { throw 'The APK IPA hash stamp does not match its bundled IPA.' }

    if ($libcxxEntry.Length -ne $expectedLibcxxBytes) {
        throw "The APK libc++_shared.so has unexpected size $($libcxxEntry.Length) bytes; expected $expectedLibcxxBytes."
    }
    $libcxxStream = $libcxxEntry.Open()
    $libcxxSha = [Security.Cryptography.SHA256]::Create()
    try { $packagedLibcxxHash = ([BitConverter]::ToString($libcxxSha.ComputeHash($libcxxStream))).Replace('-', '') }
    finally { $libcxxStream.Dispose(); $libcxxSha.Dispose() }
    if ($packagedLibcxxHash -ne $expectedLibcxxSha256) {
        throw "The APK libc++_shared.so hash $packagedLibcxxHash does not match NDK 27.2.12479018 ($expectedLibcxxSha256)."
    }

    $optionsStream = $optionsEntry.Open()
    $reader = [IO.StreamReader]::new($optionsStream, [Text.Encoding]::UTF8)
    try { $options = $reader.ReadToEnd() }
    finally { $reader.Dispose(); $optionsStream.Dispose() }
    if (-not $options.Contains($expectedOptions)) { throw 'Android default options do not enable the expected ZFR fixes.' }
    if ($options.Contains('--zf-wheel-zoom-step=') -or $options.Contains('--scale-hack=')) {
        throw 'Android defaults must use touch pinch zoom and native iPhone scale.'
    }

    Write-Host "APK: $((Resolve-Path -LiteralPath $ApkPath).Path)"
    Write-Host "IPA bytes: $($ipaEntry.Length)"
    Write-Host "IPA SHA256: $packagedHash"
    Write-Host "Android default options: PASS"
    Write-Host "arm64 touchHLE library: $($nativeEntry.Length) bytes"
    Write-Host "arm64 libc++_shared.so: $($libcxxEntry.Length) bytes, SHA256 $packagedLibcxxHash"
    Write-Host 'RESULT: PASS'
}
finally {
    $archive.Dispose()
}

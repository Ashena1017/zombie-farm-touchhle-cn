param(
    [string]$ApkPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\android\touchHLE-zombiefarm-android-arm64-fixed.apk'),
    [string]$AndroidSdk,
    [ValidateRange(1, 2100000000)][int]$ExpectedVersionCode,
    [switch]$TestBuild
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_file_hash.ps1')
$root = Split-Path -Parent $PSScriptRoot
$androidProject = Join-Path $root 'touchHLE\touchHLE-fork\android'
$releaseInfo = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $root 'release.json') | ConvertFrom-Json
if (-not $PSBoundParameters.ContainsKey('ExpectedVersionCode')) {
    $ExpectedVersionCode = $releaseInfo.android.versionCode
}
$expectedIpa = $releaseInfo.ipa
$installedName = $releaseInfo.android.installedIpaName
if ($ExpectedVersionCode -le 18) {
    # Historical APKs can be verified even when the original IPA is in cold storage.
    $ipaVersion = if ($ExpectedVersionCode -eq 18) { 'v30' } else { 'v29' }
    $report = Join-Path $root "zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-${ipaVersion}fix-notice.report.json"
    $expectedIpa = (Get-Content -Raw -Encoding UTF8 -LiteralPath $report | ConvertFrom-Json).output
    $installedName = 'Zombie_Farm_v29fix.ipa'
}
$expectedOptions = 'com.playforge.ZombieFarm.ZFR: --landscape-right --fps-limit=60 --device-family=iphone --scale-hack=3 --non-blocking-zero-timeout-run-loop'
$expectedLibcxxBytes = 1794776
$expectedLibcxxSha256 = 'F9992C4BA6B7C5A716E3A202FCEB1CE029D6A2B0605838AC6B3219F489DD7970'

if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) { throw "APK not found: $ApkPath" }
$ApkPath = (Resolve-Path -LiteralPath $ApkPath).Path

if (-not $AndroidSdk) { $AndroidSdk = $env:ANDROID_HOME }
if (-not $AndroidSdk) { $AndroidSdk = $env:ANDROID_SDK_ROOT }
if (-not $AndroidSdk) {
    $localProperties = Join-Path $androidProject 'local.properties'
    if (Test-Path -LiteralPath $localProperties -PathType Leaf) {
        $sdkLine = Select-String -LiteralPath $localProperties -Pattern '^\s*sdk\.dir\s*=\s*(.+?)\s*$' | Select-Object -First 1
        if ($sdkLine) {
            $AndroidSdk = $sdkLine.Matches[0].Groups[1].Value.Replace('\:', ':').Replace('\\', '\')
        }
    }
}
if (-not $AndroidSdk) { throw 'Set ANDROID_HOME or pass -AndroidSdk to locate Android SDK build-tools.' }
$buildTools = Get-ChildItem -LiteralPath (Join-Path $AndroidSdk 'build-tools') -Directory |
    Where-Object {
        $_.Name -match '^\d+\.\d+\.\d+$' -and
        (Test-Path -LiteralPath (Join-Path $_.FullName 'apksigner.bat') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $_.FullName 'aapt.exe') -PathType Leaf)
    } |
    Sort-Object { [version]$_.Name } -Descending |
    Select-Object -First 1
if (-not $buildTools) { throw "No SDK build-tools containing apksigner and aapt were found in $AndroidSdk." }

$managerSource = [IO.File]::ReadAllText((Join-Path $androidProject 'app\src\main\java\org\touchhle\android\ManagerActivity.java'))
$officialCertificate = [regex]::Match($managerSource, 'OFFICIAL_CERT\s*=\s*"([a-fA-F0-9]{64})"').Groups[1].Value
if (-not $officialCertificate) { throw 'Cannot read the official certificate fingerprint from ManagerActivity.java.' }

Add-Type -AssemblyName System.IO.Compression,System.IO.Compression.FileSystem
# Android asset paths are UTF-8 even when the ZIP entry lacks the language flag.
$archive = [IO.Compression.ZipFile]::Open($ApkPath, [IO.Compression.ZipArchiveMode]::Read, [Text.Encoding]::UTF8)
try {
    $ipaEntry = $archive.GetEntry("assets/$installedName")
    if (@($archive.Entries | Where-Object { $_.FullName -like 'assets/*.ipa' }).Count -ne 1) {
        throw 'Expected one bundled IPA in the official APK.'
    }
    $optionsEntry = $archive.GetEntry('assets/touchHLE_zombiefarm_options.txt')
    $hashEntry = $archive.GetEntry('assets/touchHLE_zombiefarm_ipa.sha256')
    $nativeEntry = $archive.GetEntry('lib/arm64-v8a/libtouchHLE.so')
    if ($ExpectedVersionCode -ge 21) {
        $managerEntry = $archive.GetEntry('lib/arm64-v8a/libzf_manager_mobile.so')
        if (!$managerEntry -or !$managerEntry.Length) { throw 'APK is missing the ARM64 Tauri manager.' }
    }
    $libcxxEntry = $archive.GetEntry('lib/arm64-v8a/libc++_shared.so')
    foreach ($pair in @(
        @{ Name = 'Android manifest'; Entry = $archive.GetEntry('AndroidManifest.xml') },
        @{ Name = 'main DEX'; Entry = $archive.GetEntry('classes.dex') },
        @{ Name = 'bundled IPA'; Entry = $ipaEntry },
        @{ Name = 'default options'; Entry = $optionsEntry },
        @{ Name = 'IPA hash'; Entry = $hashEntry },
        @{ Name = 'arm64 touchHLE library'; Entry = $nativeEntry },
        @{ Name = 'arm64 libc++ shared library'; Entry = $libcxxEntry }
    )) {
        if ($null -eq $pair.Entry -or $pair.Entry.Length -le 0) { throw "APK is missing $($pair.Name) or the entry is empty." }
    }

    $saveEntries = @($archive.Entries | Where-Object { $_.FullName -match '(?i)(^|/)(touchHLE_sandbox|sandbox/)|saveGame\.bin2' })
    if ($saveEntries.Count -gt 0) {
        throw "APK must not bundle player sandbox data: $(($saveEntries | ForEach-Object { $_.FullName }) -join ', ')"
    }

    $ipaStream = $ipaEntry.Open()
    try { $packagedHash = Get-Sha256Hex -Stream $ipaStream }
    finally { $ipaStream.Dispose() }
    if ($packagedHash -ne $expectedIpa.sha256 -or $ipaEntry.Length -ne $expectedIpa.size) {
        throw "The APK IPA does not match the expected $($expectedIpa.name)."
    }
    $hashStream = $hashEntry.Open()
    $hashReader = [IO.StreamReader]::new($hashStream, [Text.Encoding]::ASCII)
    try { $declaredHash = $hashReader.ReadToEnd().Trim() }
    finally { $hashReader.Dispose(); $hashStream.Dispose() }
    if ($declaredHash -ne $packagedHash) { throw 'The APK IPA hash stamp does not match its bundled IPA.' }

    if ($libcxxEntry.Length -ne $expectedLibcxxBytes) {
        throw "The APK libc++_shared.so has unexpected size $($libcxxEntry.Length) bytes; expected $expectedLibcxxBytes."
    }
    $libcxxStream = $libcxxEntry.Open()
    try { $packagedLibcxxHash = Get-Sha256Hex -Stream $libcxxStream }
    finally { $libcxxStream.Dispose() }
    if ($packagedLibcxxHash -ne $expectedLibcxxSha256) {
        throw "The APK libc++_shared.so hash $packagedLibcxxHash does not match NDK 27.2.12479018 ($expectedLibcxxSha256)."
    }

    $optionsStream = $optionsEntry.Open()
    $reader = [IO.StreamReader]::new($optionsStream, [Text.Encoding]::UTF8)
    try { $options = $reader.ReadToEnd() }
    finally { $reader.Dispose(); $optionsStream.Dispose() }
    if (-not $options.Contains($expectedOptions)) { throw 'Android default options do not enable the expected ZFR fixes.' }
    if ($options.Contains('--zf-wheel-zoom-step=')) {
        throw 'Android defaults must use touch pinch zoom.'
    }

    Write-Host "APK: $ApkPath"
    Write-Host "IPA bytes: $($ipaEntry.Length)"
    Write-Host "IPA SHA256: $packagedHash"
    Write-Host "Android default options: PASS"
    Write-Host "arm64 touchHLE library: $($nativeEntry.Length) bytes"
    Write-Host "arm64 libc++_shared.so: $($libcxxEntry.Length) bytes, SHA256 $packagedLibcxxHash"
}
finally {
    $archive.Dispose()
}

$badging = & (Join-Path $buildTools.FullName 'aapt.exe') dump badging $ApkPath
if ($LASTEXITCODE -ne 0) { throw "aapt could not inspect the APK (exit $LASTEXITCODE)." }
$badgingText = $badging -join "`n"
$manifestPackage = [regex]::Match($badgingText, "(?m)^package: name='([^']+)' versionCode='(\d+)'")
if (-not $manifestPackage.Success -or $manifestPackage.Groups[1].Value -cne 'org.touchhle.zombiefarm') {
    throw 'The APK must have application ID org.touchhle.zombiefarm.'
}
$versionCode = [int]$manifestPackage.Groups[2].Value
if ($versionCode -ne $ExpectedVersionCode) {
    throw "APK versionCode is $versionCode; expected $ExpectedVersionCode."
}
if ($badgingText -cnotmatch "(?m)^launchable-activity: name='org\.touchhle\.android\.ManagerActivity'") {
    throw 'The APK does not declare the Zombie Farm manager as a launchable activity.'
}
if ($badgingText -cnotmatch "(?m)^native-code: 'arm64-v8a'\s*$") {
    throw 'The APK must contain only arm64-v8a native code.'
}

$signing = & (Join-Path $buildTools.FullName 'apksigner.bat') verify --print-certs $ApkPath
if ($LASTEXITCODE -ne 0) { throw "APK signature verification failed (exit $LASTEXITCODE)." }
$signers = [regex]::Matches(($signing -join "`n"), '(?m)^Signer #\d+ certificate SHA-256 digest:\s*([a-fA-F0-9]{64})\s*$')
if ($signers.Count -ne 1) { throw 'The APK must have exactly one signing certificate.' }
$actualCertificate = $signers[0].Groups[1].Value
if (-not $TestBuild -and $actualCertificate -ne $officialCertificate) {
    throw "The APK signing certificate is $actualCertificate; expected the official certificate $officialCertificate."
}

Write-Host "Android application ID: $($manifestPackage.Groups[1].Value)"
Write-Host "Android versionCode: $versionCode"
Write-Host "Android signing certificate SHA-256: $actualCertificate"
Write-Host 'RESULT: PASS'

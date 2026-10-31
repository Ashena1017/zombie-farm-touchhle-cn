# Restore the Android SDK pieces the APK build needs.
#
# Why this exists: the toolchain lives under %TEMP%, and Windows storage
# cleanup deletes large binaries from it while leaving the folder tree in
# place. The next build then dies with "gradle.bat not found" or a missing
# libc++_shared.so, which looks like a project problem and is not. This
# reinstalls exactly what app/build.gradle.kts asks for (compileSdk 31,
# ndkVersion 27.2.12479018, build-tools 35.0.0) and verifies the result.
#
# JDK and Gradle are expected to be reachable too (the build script wants them
# under the same toolchain folder; a junction to the permanent copies works).
param(
    [string]$Toolchain = (Join-Path $env:TEMP 'zfr-android-toolchain'),
    [string]$Jdk = 'C:\Haven\Tools\jdk\jdk-17.0.20.1+1'
)
$ErrorActionPreference = 'Stop'
$sdk = Join-Path $Toolchain 'android'
$sdkManager = Join-Path $sdk 'cmdline-tools\latest\bin\sdkmanager.bat'

if (-not (Test-Path -LiteralPath $Jdk)) { throw "missing JDK: $Jdk" }
$env:JAVA_HOME = $Jdk
$env:PATH = (Join-Path $Jdk 'bin') + ';' + $env:PATH

if (-not (Test-Path -LiteralPath $sdkManager)) {
    $zip = Join-Path $env:TEMP ('cmdline-tools-' + [Guid]::NewGuid().ToString('N') + '.zip')
    $url = 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip'
    Write-Host "downloading $url"
    # curl rather than Invoke-WebRequest: the .NET HTTP stack aborts this large
    # download with "unexpected EOF or 0 bytes from the transport stream" on this
    # machine, while curl finishes it. -C - resumes across retries.
    $curl = 'C:\Program Files\Git\mingw64\bin\curl.exe'
    if (Test-Path -LiteralPath $curl) {
        & $curl -L --fail --retry 8 --retry-all-errors --retry-delay 3 -C - -o $zip $url
        if ($LASTEXITCODE -ne 0) { throw "curl failed with exit code $LASTEXITCODE" }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    }
    $stage = Join-Path $env:TEMP ('cmdline-stage-' + [Guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
    $dst = Join-Path $sdk 'cmdline-tools\latest'
    if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Move-Item -LiteralPath (Join-Path $stage 'cmdline-tools') -Destination $dst
    Remove-Item -LiteralPath $zip -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $sdkManager)) { throw "sdkmanager still missing: $sdkManager" }

# License prompts: answer yes for every family the packages below need.
$answers = Join-Path $env:TEMP ('lic-' + [Guid]::NewGuid().ToString('N') + '.txt')
[System.IO.File]::WriteAllText($answers, ((1..80 | ForEach-Object { 'y' }) -join "`r`n"))
Write-Host '--- accepting licenses ---'
& cmd /c "`"$sdkManager`" --sdk_root=`"$sdk`" --licenses < `"$answers`""
Remove-Item -LiteralPath $answers -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '--- installing packages ---'
& cmd /c "`"$sdkManager`" --sdk_root=`"$sdk`" `"platforms;android-31`" `"build-tools;35.0.0`" `"ndk;27.2.12479018`" `"platform-tools`""
if ($LASTEXITCODE -ne 0) { throw "sdkmanager failed with exit code $LASTEXITCODE" }

Write-Host ''
Write-Host '--- verifying ---'
$checks = @(
    @{ Name = 'platform android-31'; Path = (Join-Path $sdk 'platforms\android-31\android.jar') },
    @{ Name = 'aapt2';               Path = (Join-Path $sdk 'build-tools\35.0.0\aapt2.exe') },
    @{ Name = 'd8';                  Path = (Join-Path $sdk 'build-tools\35.0.0\d8.bat') },
    @{ Name = 'apksigner';           Path = (Join-Path $sdk 'build-tools\35.0.0\apksigner.bat') },
    @{ Name = 'ndk-build';           Path = (Join-Path $sdk 'ndk\27.2.12479018\ndk-build.cmd') },
    @{ Name = 'ndk source.properties'; Path = (Join-Path $sdk 'ndk\27.2.12479018\source.properties') },
    @{ Name = 'libc++_shared.so';    Path = (Join-Path $sdk 'ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\sysroot\usr\lib\aarch64-linux-android\libc++_shared.so') }
)
$missing = 0
foreach ($check in $checks) {
    $ok = Test-Path -LiteralPath $check.Path
    if (-not $ok) { $missing++ }
    Write-Host ("  {0,-30} {1}" -f $check.Name, $(if ($ok) { 'ok' } else { 'MISSING' }))
}
if ($missing -gt 0) { throw "$missing SDK piece(s) still missing" }
Write-Host ''
Write-Host 'DONE: Android SDK restored'

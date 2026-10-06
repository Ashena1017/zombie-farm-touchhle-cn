$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$toolchain = 'C:\Users\Loner\AppData\Local\Temp\zfr-android-toolchain'
$repoTools = Join-Path $root 'touchHLE\_build_tools'
$gradle = Join-Path $toolchain 'gradle-8.11.1\bin\gradle.bat'
$jdk = Join-Path $toolchain 'jdk17'

foreach ($required in @(
    (Join-Path $jdk 'bin\java.exe'),
    $gradle,
    (Join-Path $repoTools 'cargo\bin\cargo.exe'),
    (Join-Path $toolchain 'android\platform-tools\adb.exe')
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Android build dependency not found: $required"
    }
}

$env:JAVA_HOME = $jdk
$env:GRADLE_USER_HOME = Join-Path $toolchain 'gradle-home'
$env:CARGO_HOME = Join-Path $repoTools 'cargo'
$env:RUSTUP_HOME = Join-Path $repoTools 'rustup'
$env:ANDROID_HOME = Join-Path $toolchain 'android'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = @(
    (Join-Path $jdk 'bin'),
    (Join-Path $toolchain 'gradle-8.11.1\bin'),
    (Join-Path $repoTools 'cargo\bin'),
    (Join-Path $env:ANDROID_HOME 'platform-tools'),
    $env:PATH
) -join ';'

& (Join-Path $PSScriptRoot '_build_android.ps1') -Gradle $gradle
if ($LASTEXITCODE -ne 0) {
    throw "Android build failed with exit code $LASTEXITCODE."
}

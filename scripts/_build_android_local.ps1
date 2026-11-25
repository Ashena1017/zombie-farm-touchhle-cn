param(
    # Forwarded to the inner build: dependency cache only, no network resolves.
    [switch]$Offline,
    [switch]$TestBuild,
    [string]$AndroidSdk = 'C:\Haven\Tools\android-sdk',
    [string]$Jdk = 'C:\Haven\Tools\jdk\jdk-17.0.20.1+1',
    [string]$Gradle = (Join-Path $env:USERPROFILE '.gradle\manual-gradle-8.11.1\bin\gradle.bat')
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$repoTools = Join-Path $root 'touchHLE\_build_tools'

foreach ($required in @(
    (Join-Path $jdk 'bin\java.exe'),
    $gradle,
    (Join-Path $repoTools 'cargo\bin\cargo.exe'),
    (Join-Path $AndroidSdk 'platform-tools\adb.exe')
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Android build dependency not found: $required"
    }
}

$env:JAVA_HOME = $jdk
$env:CARGO_HOME = Join-Path $repoTools 'cargo'
$env:RUSTUP_HOME = Join-Path $repoTools 'rustup'
$env:ANDROID_HOME = $AndroidSdk
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = @(
    (Join-Path $jdk 'bin'),
    (Split-Path -Parent $Gradle),
    (Join-Path $env:ProgramFiles 'Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja'),
    (Join-Path $repoTools 'cargo\bin'),
    (Join-Path $env:ANDROID_HOME 'platform-tools'),
    $env:PATH
) -join ';'

& (Join-Path $PSScriptRoot '_build_android.ps1') -Gradle $gradle -Offline:$Offline -TestBuild:$TestBuild
if ($LASTEXITCODE -ne 0) {
    throw "Android build failed with exit code $LASTEXITCODE."
}

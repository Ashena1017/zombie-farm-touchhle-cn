# Build the Android Tauri library before Gradle configures its generated Kotlin sources.
param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$android = Join-Path $root 'touchHLE/touchHLE-fork/android'
$generated = Join-Path $android '.tauri'
$env:WRY_ANDROID_PACKAGE = 'org.touchhle.android'
$env:WRY_ANDROID_LIBRARY = 'zf_manager_mobile'
$env:WRY_ANDROID_KOTLIN_FILES_OUT_DIR = Join-Path $generated 'kotlin'
$env:TAURI_ANDROID_PROJECT_PATH = $android
$env:ANDROID_NDK_HOME = Join-Path $env:ANDROID_HOME 'ndk/27.2.12479018'
New-Item -ItemType Directory -Force $env:WRY_ANDROID_KOTLIN_FILES_OUT_DIR | Out-Null
$extra = @()
if ($Offline) { $extra += '--offline' }
Push-Location (Join-Path $root 'windows/launcher')
try {
    & cargo ndk -t arm64-v8a -p 21 -o (Join-Path $generated 'jni') build --release --locked --lib @extra
    if ($LASTEXITCODE) { throw "Tauri Android build failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}

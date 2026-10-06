param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$toolchain = 'C:\Users\Loner\AppData\Local\Temp\zfr-android-toolchain'
$env:JAVA_HOME = Join-Path $toolchain 'jdk17'
$env:GRADLE_USER_HOME = Join-Path $toolchain 'gradle-home'
$env:CARGO_HOME = Join-Path $root 'touchHLE\_build_tools\cargo'
$env:RUSTUP_HOME = Join-Path $root 'touchHLE\_build_tools\rustup'
$env:ANDROID_HOME = Join-Path $toolchain 'android'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = (Join-Path $env:JAVA_HOME 'bin') + ';' + (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:PATH
$android = Join-Path $root 'touchHLE\touchHLE-fork\android'
$buildLog = Join-Path $PSScriptRoot 'dumps\android-manager-test-build.txt'
if (-not $SkipBuild) {
    $ErrorActionPreference = 'Continue'
    & (Join-Path $toolchain 'gradle-8.11.1\bin\gradle.bat') --project-dir $android :app:assembleReleaseAndroidTest *> $buildLog
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) {
        Get-Content -LiteralPath $buildLog -Encoding UTF8 -Tail 35
        throw 'Android manager test APK build failed.'
    }
}
$adb = 'C:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe'
& $adb connect 127.0.0.1:5557
$testApk = Join-Path $android 'app\build\outputs\apk\androidTest\release\app-release-androidTest.apk'
& $adb -s 127.0.0.1:5557 install -r $testApk
if ($LASTEXITCODE -ne 0) { throw 'Android manager test APK install failed.' }
$result = (& $adb -s 127.0.0.1:5557 shell am instrument -w org.touchhle.zombiefarm.test/org.touchhle.android.ManagerTestRunner) -join "`n"
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'dumps\android-manager-tests.txt'), $result, [Text.UTF8Encoding]::new($false))
Write-Output $result
if ($result -notmatch 'RESULT: PASS' -or $result -match 'RESULT: FAIL|INSTRUMENTATION_FAILED') {
    throw 'Android manager isolated-fixture tests failed.'
}

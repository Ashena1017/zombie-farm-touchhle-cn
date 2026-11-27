param(
    [string]$Serial = $env:ANDROID_SERIAL,
    [string]$AndroidSdk = $(if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { 'C:\Haven\Tools\android-sdk' }),
    [string]$OutputDir = (Join-Path $PSScriptRoot 'dumps\device-build'),
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $SkipBuild) {
    & (Join-Path $root 'scripts\_build_android_local.ps1') -TestBuild -WithDeviceTests -AndroidSdk $AndroidSdk -OutputDir $OutputDir
}
$adb = Join-Path $AndroidSdk 'platform-tools\adb.exe'
$device = @()
if ($Serial) { $device = @('-s', $Serial) }
& $adb @device get-state
if ($LASTEXITCODE) { throw 'Select a connected Android device with -Serial.' }
foreach ($name in @('touchHLE-zombiefarm-android-arm64-test.apk', 'manager-instrumentation.apk')) {
    & $adb @device install -r (Join-Path $OutputDir "test\$name")
    if ($LASTEXITCODE) { throw "Could not install $name." }
}
$result = (& $adb @device shell am instrument -w org.touchhle.zombiefarm.qa.test/org.touchhle.android.ManagerTestRunner) -join "`n"
[void][IO.Directory]::CreateDirectory((Join-Path $PSScriptRoot 'dumps'))
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'dumps\android-manager-tests.txt'), $result, [Text.UTF8Encoding]::new($false))
Write-Output $result
if ($result -notmatch 'RESULT: PASS' -or $result -match 'RESULT: FAIL|INSTRUMENTATION_FAILED') {
    throw 'Android manager isolated-fixture tests failed.'
}

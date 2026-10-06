# Confirm every emulator resource resolves through $hleRoot after the reorganisation.
# Read-only.
$root = Split-Path -Parent $PSScriptRoot

$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

Write-Host "root    : $root"
Write-Host "hleRoot : $hleRoot"
Write-Host ''

$checks = @(
    @{ Name = 'touchHLE.exe';            Path = (Join-Path $hleRoot 'touchHLE.exe') }
    @{ Name = 'touchHLE_fork.exe';       Path = (Join-Path $hleRoot 'touchHLE_fork.exe') }
    @{ Name = 'touchHLE_dylibs';         Path = (Join-Path $hleRoot 'touchHLE_dylibs') }
    @{ Name = 'touchHLE_fonts';          Path = (Join-Path $hleRoot 'touchHLE_fonts') }
    @{ Name = 'touchHLE_sandbox';        Path = (Join-Path $hleRoot 'touchHLE_sandbox') }
    @{ Name = 'touchHLE_options.txt';    Path = (Join-Path $hleRoot 'touchHLE_options.txt') }
    @{ Name = 'touchHLE_default_options';Path = (Join-Path $hleRoot 'touchHLE_default_options.txt') }
    @{ Name = 'zfr_last_run.log';        Path = (Join-Path $hleRoot 'zfr_last_run.log') }
    @{ Name = 'zfr_last_launch.txt';     Path = (Join-Path $hleRoot 'zfr_last_launch.txt') }
    @{ Name = 'time_offset_seconds.txt'; Path = (Join-Path $hleRoot 'touchHLE_time_offset_seconds.txt') }
    @{ Name = 'touchHLE-fork/src';       Path = (Join-Path $hleRoot 'touchHLE-fork\src') }
    # The upstream trunk was deleted on purpose (it carried an injected
    # AGENTS.md/CLAUDE.md, and the fork no longer depends on it - its vendor
    # deps used to be junctions into the trunk and are now real directories).
    @{ Name = 'touchHLE-fork/vendor';    Path = (Join-Path $hleRoot 'touchHLE-fork\vendor\stb') }
    @{ Name = '_build_tools';            Path = (Join-Path $hleRoot '_build_tools') }
    @{ Name = 'LICENSE';                 Path = (Join-Path $hleRoot 'LICENSE') }
    @{ Name = 'zombie_farm_ipa';             Path = (Join-Path $root 'zombie_farm_ipa') }
    @{ Name = 'tools';                   Path = (Join-Path $root 'tools') }
    @{ Name = '_analysis';               Path = (Join-Path $root '_analysis') }
    @{ Name = 'Release';                 Path = (Join-Path $root 'Release') }
    @{ Name = 'GameManager.ps1';         Path = (Join-Path $root 'GameManager.ps1') }
    @{ Name = '游戏管理.exe';             Path = (Join-Path $root '游戏管理.exe') }
)

$fail = 0
foreach ($c in $checks) {
    $ok = Test-Path -LiteralPath $c.Path
    if (-not $ok) { $fail++ }
    Write-Host ("  {0,-24} {1}" -f $c.Name, $(if ($ok) { 'ok' } else { 'MISSING' }))
}

# Nothing emulator-shaped may sit in the root any more.
Write-Host ''
Write-Host '--- root must be free of emulator files ---'
$stray = @(Get-ChildItem -LiteralPath $root -Force |
    Where-Object {
        $_.Name -match '^touchHLE|^zfr|^_build_tools' -and
        $_.Name -ne 'touchHLE' -and
        $_.Name -ne 'touchHLE-zombiefarm-android-arm64'
    })
if ($stray.Count) {
    $fail++
    foreach ($s in $stray) { Write-Host "  STRAY: $($s.Name)" }
} else {
    Write-Host '  no stray emulator files in the root'
}

Write-Host ''
if ($fail) {
    Write-Host "RESULT: FAIL ($fail)"
    exit 1
}
Write-Host 'RESULT: PASS - every path resolves through $hleRoot'

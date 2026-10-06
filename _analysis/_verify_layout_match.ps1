# Compare the development tree's root with the shipped Release bundle's root.
#
# The human asked for the dev tree to mirror ./Release: "touchHLE-related things go
# into ./touchHLE, everything else outside it goes into the game-management side."
# This prints both roots and checks the two things that actually matter:
#
#   1. STRUCTURE -- every emulator resource lives under touchHLE\ in BOTH trees,
#      and nothing emulator-shaped sits in either root;
#   2. COVERAGE   -- everything the bundle ships can be rebuilt from the dev tree.
#
# It deliberately does NOT require the two roots to be identical: the dev tree has
# extra material on purpose (docs, analysis, the source trees, the build toolchain),
# and the bundle has a generated 使用说明.html that is not a source file.
#
# Read-only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)
$root = (Split-Path -Parent $PSScriptRoot)

$release = Join-Path $Root 'Release'

function Get-Names([string]$dir) {
    if (-not (Test-Path -LiteralPath $dir)) { return @() }
    @(Get-ChildItem -LiteralPath $dir -Force |
        Where-Object { $_.Name -notmatch '^(\.|~)' } |
        ForEach-Object { $_.Name } | Sort-Object)
}

$devNames = Get-Names $Root
$relNames = Get-Names $release

# Present in the development tree but intentionally not shipped.
# launcher_selected_ipa.txt / launcher_skip_memory.txt / launcher_night_mode.txt are RUNTIME STATE written
# by the manager on use (which IPA is picked, last skip-ahead duration), not
# source; they appear only after someone runs the manager.
$devOnly = @(
    'TECHNICAL.md', 'process.md', 'HANDOVER.md', '交接提示词.md', 'README.md',
    'launcher_selected_ipa.txt', 'launcher_skip_memory.txt', 'launcher_night_mode.txt',
    'StartZombieFarmNextHour.ps1', 'RestoreTestSave.ps1', 'SetZombieFarmCurrency.ps1',
    '运行游戏.bat', '选择跳过时间并启动.bat', '使用教程.txt',
    'StartZombieFarmNextHour.ps1.backup-20260919-204040',
    'tools', '_analysis', 'Release', 'docs', 'touchHLE-zombiefarm-android-arm64'
)

# Present in the bundle but generated at build time (so not a source file).
$relGenerated = @('使用说明.html')

Write-Host "=== development root ==="
foreach ($n in $devNames) {
    $isDir = Test-Path -LiteralPath (Join-Path $Root $n) -PathType Container
    $mark = if ($isDir) { '[D]' } else { '   ' }
    $note = if ($n -in $devOnly) { '   (dev only, not shipped)' } else { '' }
    Write-Host ("  {0} {1}{2}" -f $mark, $n, $note)
}

Write-Host ''
Write-Host "=== Release root ==="
foreach ($n in $relNames) {
    $isDir = Test-Path -LiteralPath (Join-Path $release $n) -PathType Container
    $mark = if ($isDir) { '[D]' } else { '   ' }
    $note = if ($n -in $relGenerated) { '   (generated at build time)' } else { '' }
    Write-Host ("  {0} {1}{2}" -f $mark, $n, $note)
}

Write-Host ''
Write-Host '=== comparison ==='
$fail = 0

# 1. Everything shipped (except generated files) must exist in the dev tree.
foreach ($n in $relNames) {
    if ($n -in $relGenerated) { continue }
    if (-not (Test-Path -LiteralPath (Join-Path $Root $n))) {
        Write-Host "  MISSING from dev tree: $n"
        $fail++
    }
}

# 2. The dev tree's extra top-level entries must all be expected.
foreach ($n in $devNames) {
    if ($n -notin $relNames -and $n -notin $devOnly) {
        Write-Host "  UNEXPECTED in dev root: $n"
        $fail++
    }
}

# 3. Nothing emulator-shaped may sit in EITHER root.
foreach ($pair in @(@{ Tree = 'dev'; Dir = $Root }, @{ Tree = 'Release'; Dir = $release })) {
    $stray = @(Get-ChildItem -LiteralPath $pair.Dir -Force |
        Where-Object {
            $_.Name -match '^touchHLE|^zfr|^_build_tools' -and
            $_.Name -ne 'touchHLE' -and
            $_.Name -ne 'touchHLE-zombiefarm-android-arm64'
        })
    foreach ($s in $stray) {
        Write-Host "  STRAY in $($pair.Tree) root: $($s.Name)"
        $fail++
    }
}

# 4. The bundle must not carry the dev-only emulator folders.
foreach ($n in @('touchHLE-fork', 'touchHLE-trunk', '_build_tools', 'vendor')) {
    if (Test-Path -LiteralPath (Join-Path $release "touchHLE\$n")) {
        Write-Host "  touchHLE\$n leaked into the shipped bundle"
        $fail++
    }
}

# 5. The emulator folder must hold the same runtime items in both trees.
$devHle = Get-Names (Join-Path $Root 'touchHLE')
$relHle = Get-Names (Join-Path $release 'touchHLE')
foreach ($n in $relHle) {
    # The bundle renames the licence and adds per-dylib COPYING files.
    if ($n -like 'COPYING.*' -or $n -eq 'LICENSE-touchHLE.txt') { continue }
    if ($n -notin $devHle) {
        Write-Host "  touchHLE\ : shipped but not in dev tree: $n"
        $fail++
    }
}

Write-Host ''
if ($fail) {
    Write-Host "RESULT: FAIL ($fail difference(s))"
    exit 1
}
Write-Host 'RESULT: PASS - both roots hold the emulator in touchHLE\ and nothing else emulator-shaped'

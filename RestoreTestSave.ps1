# Restore the "known good" save before a test run.
#
# The sandbox save is only written on a clean in-game exit, and every invasion /
# ability unlock consumes state (e.g. the pool of abilities still to unlock), so
# repeated tests drift.  `saveGame.bin2.bak` is the user's frozen reference save;
# this script swaps it in, first archiving whatever is currently live so nothing
# is ever lost.
#
#   .\RestoreTestSave.ps1              # archive live save, restore the .bak
#   .\RestoreTestSave.ps1 -Force       # do not ask (for scripted use)
#   .\RestoreTestSave.ps1 -List        # show what is available
param(
    [switch]$Force,
    [switch]$List
)

$ErrorActionPreference = 'Stop'

# The emulator lives in its own folder now (the tree mirrors the shipped ./Release
# layout). Fall back to the flat layout so this keeps working either way.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'touchHLE\touchHLE.exe')) {
    Join-Path $PSScriptRoot 'touchHLE'
} else {
    $PSScriptRoot
}

$docs = Join-Path $hleRoot 'touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents'
$live = Join-Path $docs 'saveGame.bin2'
$ref = Join-Path $docs 'saveGame.bin2.bak'

if (-not (Test-Path -LiteralPath $docs)) {
    throw "Sandbox Documents folder not found: $docs"
}

if ($List) {
    Get-ChildItem -LiteralPath $docs -Filter 'saveGame.bin2*' |
        Sort-Object LastWriteTime -Descending |
        Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
    return
}

if (-not (Test-Path -LiteralPath $ref)) {
    throw "Reference save not found: $ref"
}

if (-not (Test-Path -LiteralPath $live)) {
    throw "Live save not found: $live"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archive = Join-Path $docs "saveGame.bin2.bak-$stamp-pre-restore"

if (-not $Force) {
    Write-Host "This will:"
    Write-Host "  1. archive the live save as $(Split-Path -Leaf $archive)"
    Write-Host "  2. copy $(Split-Path -Leaf $ref) over the live save"
    $answer = Read-Host 'Continue? [y/N]'
    if ($answer -notmatch '^[Yy]') {
        Write-Host 'Aborted.'
        return
    }
}

Move-Item -LiteralPath $live -Destination $archive
Copy-Item -LiteralPath $ref -Destination $live

Write-Host "Archived live save -> $(Split-Path -Leaf $archive)"
Write-Host "Restored reference save -> saveGame.bin2 ($((Get-Item -LiteralPath $live).Length) bytes)"

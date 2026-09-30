# Install touchHLE_fork.exe as the launcher's touchHLE, so the game runs at 60fps.
#
# What this does:
#   1. Backs up the current touchHLE.exe (keeping the sha256 so the swap is
#      reversible and provable).
#   2. Copies touchHLE_fork.exe over touchHLE.exe.
#   3. Adds the --non-blocking-zero-timeout-run-loop option to the launcher.
#
# The launcher already passes --device-family=ipad --landscape-right; the new
# option is appended there so every launch path (运行游戏.bat,
# 选择跳过时间并启动.bat, and direct StartZombieFarmNextHour.ps1 calls) gets it.
param(
    [switch]$Revert,
    [switch]$DryRun
)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

$ErrorActionPreference = 'Stop'

$root  = (Split-Path -Parent $PSScriptRoot)
$live  = Join-Path $hleRoot 'touchHLE.exe'
$new   = Join-Path $hleRoot 'touchHLE_fork.exe'
$lch   = Join-Path $root 'StartZombieFarmNextHour.ps1'
$log   = Join-Path $root '_analysis\_install.log'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $hleRoot "touchHLE.exe.backup-fps60-$stamp"
$optMarker = '--non-blocking-zero-timeout-run-loop'

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $log -Value $m -Encoding utf8
}
Add-Content -LiteralPath $log -Value "`n===== install run $stamp (Revert=$Revert DryRun=$DryRun) =====" -Encoding utf8

if ($Revert) {
    $baks = Get-ChildItem $hleRoot -Filter 'touchHLE.exe.backup-fps60-*' | Sort-Object Name -Descending
    if (-not $baks) { throw 'No fps60 backup found; nothing to revert.' }
    $pick = $baks[0]
    Log "restoring $($pick.Name) -> touchHLE.exe"
    if (-not $DryRun) {
        Copy-Item -LiteralPath $pick.FullName -Destination $live -Force
        # remove the option again
        $t = Get-Content -LiteralPath $lch -Raw
        $t2 = $t -replace "(?m)\s*'$([regex]::Escape($optMarker))'", ''
        if ($t2 -ne $t) { Set-Content -LiteralPath $lch -Value $t2 -NoNewline -Encoding utf8 }
        Log 'removed the option from the launcher'
    }
    Log 'REVERTED'
    exit 0
}

if (-not (Test-Path $new)) { throw "missing $new" }
if (-not (Test-Path $live)) { throw "missing $live" }
if (-not (Test-Path $lch)) { throw "missing $lch" }

$oldHash = (Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
$newHash = (Get-FileHash -LiteralPath $new  -Algorithm SHA256).Hash
$oldSize = (Get-Item $live).Length
$newSize = (Get-Item $new).Length
Log "current touchHLE.exe : $oldSize bytes  sha256=$oldHash"
Log "new     touchHLE.exe : $newSize bytes  sha256=$newHash"

if ($oldHash -eq $newHash) {
    Log 'already identical; only ensuring the launcher option is present.'
} else {
    Log "backing up to $(Split-Path -Leaf $backup)"
    if (-not $DryRun) { Copy-Item -LiteralPath $live -Destination $backup -Force }
}

# --- launcher option ------------------------------------------------------
$launcher = Get-Content -LiteralPath $lch -Raw
if ($launcher -match [regex]::Escape($optMarker)) {
    Log 'launcher already passes the option'
} else {
    # the launch line ends with:  & $touchHLE $game '--device-family=ipad' '--landscape-right'
    $pattern = "('\-\-landscape-right')"
    if ($launcher -notmatch $pattern) {
        throw "could not find the '--landscape-right' argument in $lch; edit it manually"
    }
    $replacement = "`$1 '$optMarker'"
    $updated = $launcher -replace $pattern, $replacement
    if ($updated -eq $launcher) { throw 'launcher unchanged; aborting' }
    Log "launcher: appending '$optMarker' after '--landscape-right'"
    if (-not $DryRun) {
        Copy-Item -LiteralPath $lch -Destination "$lch.backup-$stamp" -Force
        Set-Content -LiteralPath $lch -Value $updated -NoNewline -Encoding utf8
    }
    # show the resulting launch line
    ($updated -split "`n") | Where-Object { $_ -match 'touchHLE \$game' } | ForEach-Object { Log ("  now: " + $_.Trim()) }
}

# --- swap the binary ------------------------------------------------------
if ($oldHash -ne $newHash) {
    if ($DryRun) {
        Log "DRY RUN: would copy $new -> $live"
    } else {
        Copy-Item -LiteralPath $new -Destination $live -Force
        $check = (Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash
        Log "installed: touchHLE.exe sha256=$check"
        if ($check -ne $newHash) { throw 'hash mismatch after install!' }
    }
}

Log 'DONE. Undo with: .\_analysis\_install_fps60.ps1 -Revert'

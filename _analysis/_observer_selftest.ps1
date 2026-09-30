# Verify the stale-notification-observer cleanup with a self-test, no gameplay.
#
# The emulator's own build has a one-shot self-test
# (TOUCHHLE_NSNOTIFICATIONCENTER_STALE_SELFTEST=1): as soon as the guest
# registers its first notification observer, it registers a throwaway NSObject
# for "incrementCount:", deallocates it while it is still registered (what
# Zombie Farm's quest requirements do), reuses the freed address with strings,
# and posts the notification.
#
#   - with the cleanup disabled (TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE=1)
#     the post sends incrementCount: to whatever now lives at that address, so
#     emulation aborts exactly like the reported crash;
#   - with the cleanup enabled the stale entry is dropped and the run continues.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Tag = 'selftest',
    [int]$Seconds = 50,
    [switch]$NoPrune
)
$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}


$ErrorActionPreference = 'Continue'

$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-final-nonexistent.ipa'
$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$hle = Join-Path $hleRoot 'touchHLE_fork.exe'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$outLog = Join-Path $Root ("_analysis\perf\selftest_$Tag.out.log")

foreach ($f in @($ipa, $hle, $sandbox)) {
    if (-not (Test-Path -LiteralPath $f)) { Write-Host "FAIL: missing $f"; exit 1 }
}

$snap = Join-Path $env:TEMP ('zfrt_' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force
Remove-Item -LiteralPath $outLog -Force -ErrorAction SilentlyContinue

$env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
$env:TOUCHHLE_NSNOTIFICATIONCENTER_STALE_SELFTEST = '1'
Remove-Item Env:TOUCHHLE_NSNOTIFICATIONCENTER_STALE_AUDIT -ErrorAction SilentlyContinue
Remove-Item Env:TOUCHHLE_ZFR_DEBUG_COMPLETE_QUESTS_AFTER -ErrorAction SilentlyContinue
Remove-Item Env:TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION -ErrorAction SilentlyContinue
if ($NoPrune) {
    $env:TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE = '1'
} else {
    Remove-Item Env:TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE -ErrorAction SilentlyContinue
}
Write-Host ("pruning: " + $(if ($NoPrune) { 'DISABLED (expect an abort)' } else { 'enabled (expect cleanup)' }))

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/c ""{0}" "{1}" --landscape-right > "{2}" 2>&1"' -f $hle, $ipa, $outLog
# MUST be touchHLE's own folder: it resolves touchHLE_dylibs/ etc. against the
# CURRENT DIRECTORY (src/paths.rs), not the executable's location.
$psi.WorkingDirectory = $hleRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)
$startTime = Get-Date
Write-Host "started cmd pid $($proc.Id); running for up to $Seconds s"

$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline -and -not $proc.HasExited) { Start-Sleep -Seconds 2 }

$exited = $proc.HasExited
if (-not $exited) {
    Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}
Write-Host ("process exited on its own: " + $(if ($exited) { "yes (code $($proc.ExitCode))" } else { 'no (killed after the timeout)' }))

$hleLog = Join-Path $hleRoot 'touchHLE_log.txt'
$text = ''
if (Test-Path -LiteralPath $outLog) { $text = [System.IO.File]::ReadAllText($outLog) }
if (Test-Path -LiteralPath $hleLog) {
    $hleText = [System.IO.File]::ReadAllText($hleLog)
    Copy-Item -LiteralPath $hleLog -Destination (Join-Path $Root ("_analysis\perf\selftest_$Tag.touchhle.log")) -Force
    if ($hleText.Length -gt $text.Length) { $text = $hleText }
}
$lines = $text -split "`r?`n"

Write-Host ''
Write-Host '--- self-test output ---'
foreach ($l in ($lines | Select-String -Pattern 'self-test|Skipping stale|does not respond to selector|panicked')) {
    Write-Host ('    ' + $l.Line.Trim())
}

$aborted = ($lines | Select-String -Pattern 'does not respond to selector|panicked at') -ne $null
$cleaned = ($lines | Select-String -Pattern 'Skipping stale NSNotificationCenter observer') -ne $null
$posted = ($lines | Select-String -Pattern 'posted without aborting') -ne $null

Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $hleLog -Force -ErrorAction SilentlyContinue
Write-Host 'sandbox restored'

Write-Host ''
if ($NoPrune) {
    $good = $aborted
    Write-Host ("RESULT: " + $(if ($good) { 'PASS - reproduced the abort with pruning off' } else { 'INCONCLUSIVE' }))
} else {
    $good = $cleaned -and $posted -and -not $aborted
    Write-Host ("RESULT: " + $(if ($good) { 'PASS - stale observer was cleaned up and the run survived' } else { 'FAIL' }))
}
exit $(if ($good) { 0 } else { 1 })

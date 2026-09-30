# Boot a given IPA with touchHLE and report whether it survives.
#
# Why this matters for v28fix: -[ZFQuestNotification stopListening] is called by
# GameData's addUserData: / readUserData: while the save is loaded, i.e. during
# startup, BEFORE the splash screen is dismissed. If the hand-written assembly
# were wrong (bad register, unbalanced stack, wrong selector slot), the very
# first save load would panic - no gameplay needed.
#
# The sandbox is snapshotted and restored. Pure ASCII.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Ipa = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa',
    [string]$Tag = 'boot',
    [int]$Seconds = 100
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

$ipaPath = if ([System.IO.Path]::IsPathRooted($Ipa)) { $Ipa } else { Join-Path $Root ('zombie_farm_ipa\' + $Ipa) }
$hle = Join-Path $hleRoot 'touchHLE_fork.exe'
$sandbox = Join-Path $hleRoot 'touchHLE_sandbox'
$perfDir = Join-Path $Root '_analysis\perf'
$outLog = Join-Path $perfDir "boot_$Tag.out.log"

foreach ($f in @($ipaPath, $hle, $sandbox)) {
    if (-not (Test-Path -LiteralPath $f)) { Write-Host "FAIL: missing $f"; exit 1 }
}
if (-not (Test-Path -LiteralPath $perfDir)) { New-Item -ItemType Directory -Path $perfDir -Force | Out-Null }

$snap = Join-Path $env:TEMP ('zfrb_' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $sandbox -Destination $snap -Recurse -Force
Remove-Item -LiteralPath $outLog -Force -ErrorAction SilentlyContinue

$env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
# Exercise the emulator's own cleanup too, so the log tells us whether the IPA
# fix removed the dangling entries at the source (it should, hence 0 stale).
$env:TOUCHHLE_NSNOTIFICATIONCENTER_STALE_AUDIT = '20'
Remove-Item Env:TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE -ErrorAction SilentlyContinue
Remove-Item Env:TOUCHHLE_NSNOTIFICATIONCENTER_STALE_SELFTEST -ErrorAction SilentlyContinue
Remove-Item Env:TOUCHHLE_ZFR_DEBUG_COMPLETE_QUESTS_AFTER -ErrorAction SilentlyContinue
Remove-Item Env:TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION -ErrorAction SilentlyContinue

Write-Host "=== boot test: $Ipa ==="

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/c ""{0}" "{1}" --landscape-right > "{2}" 2>&1"' -f $hle, $ipaPath, $outLog
$psi.WorkingDirectory = $hleRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$proc = [System.Diagnostics.Process]::Start($psi)

$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline -and -not $proc.HasExited) { Start-Sleep -Seconds 5 }

$exited = $proc.HasExited
$code = $null
if ($exited) { $code = $proc.ExitCode }
if (-not $exited) {
    Get-Process -Name 'touchHLE*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}
Write-Host ("process exited on its own: " + $(if ($exited) { "yes (code $code)" } else { 'no (killed after the timeout) - i.e. it was still alive' }))

$hleLog = Join-Path $hleRoot 'touchHLE_log.txt'
$text = ''
if (Test-Path -LiteralPath $outLog) { $text = [System.IO.File]::ReadAllText($outLog) }
if (Test-Path -LiteralPath $hleLog) {
    $hleText = [System.IO.File]::ReadAllText($hleLog)
    Copy-Item -LiteralPath $hleLog -Destination (Join-Path $perfDir "boot_$Tag.touchhle.log") -Force
    if ($hleText.Length -gt $text.Length) { $text = $hleText }
}
$lines = $text -split "`r?`n"

function Show-Lines([string]$pattern, [int]$max) {
    $hits = @($lines | Select-String -Pattern $pattern)
    Write-Host ("--- {0}: {1} hit(s)" -f $pattern, $hits.Count)
    foreach ($h in ($hits | Select-Object -First $max)) {
        Write-Host ('    ' + $h.Line.Trim().Substring(0, [Math]::Min(150, $h.Line.Trim().Length)))
    }
}
Show-Lines 'CPU emulation begins' 2
Show-Lines 'stale audit' 8
Show-Lines 'does not respond to selector|panicked at' 6
Show-Lines 'Skipping stale' 4
Show-Lines 'stopListening|ZFR.*crash' 4

Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $snap -Destination $sandbox -Recurse -Force
Remove-Item -LiteralPath $snap -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $hleLog -Force -ErrorAction SilentlyContinue
Write-Host 'sandbox restored'

$began = ($lines | Select-String -Pattern 'CPU emulation begins') -ne $null
$panicked = ($lines | Select-String -Pattern 'does not respond to selector|panicked at') -ne $null
$good = $began -and -not $panicked -and -not $exited
Write-Host ''
Write-Host ("emulation began: {0}; panic: {1}; still alive at the end: {2}" -f $began, $panicked, (-not $exited))
Write-Host ("RESULT: " + $(if ($good) { 'PASS - booted and survived' } else { 'FAIL' }))
exit $(if ($good) { 0 } else { 1 })

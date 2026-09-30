# End-to-end test of the launcher settings: set values, launch the game through
# StartZombieFarmNextHour.ps1 exactly as the menu does, and read back the
# framerate touchHLE actually achieved.
#
# This proves the settings reach touchHLE, not merely that they were saved.
param(
    [string]$Tag = 'default',
    [string]$Settings = 'fps_limit=60,scale_hack=1,fullscreen=0,show_fps=1,non_blocking_run_loop=1',
    [int]$Seconds = 30
)

$ErrorActionPreference = 'Continue'
$root = (Split-Path -Parent $PSScriptRoot)
$perf = Join-Path $root '_analysis\perf'
$out  = Join-Path $root '_analysis\_launcher_test.log'
$gameLog = Join-Path $perf "launcher_$Tag.log"

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $out -Value $m -Encoding utf8
}
Set-Content -LiteralPath $out -Value "launcher settings test: $Tag $(Get-Date -Format o)" -Encoding utf8

# 1. apply the settings through the same code path the menu uses
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'GameManager.ps1') -Set $Settings |
    ForEach-Object { Log "  set: $_" }

# 2. restore the reference save so the run is comparable
& (Join-Path $root 'RestoreTestSave.ps1') -Force *>&1 | ForEach-Object { Log "  $_" }

Remove-Item -LiteralPath $gameLog -Force -ErrorAction SilentlyContinue

# 3. launch through the real launcher (this is what the menu option 1 does)
$job = Start-Job -ScriptBlock {
    param($root, $log)
    Set-Location -LiteralPath $root
    & powershell -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $root 'StartZombieFarmNextHour.ps1') -NoSkip *> $log
} -ArgumentList $root, $gameLog

$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 500 }
if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
Remove-Job $job -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $gameLog)) { Log '  NO GAME LOG'; exit 1 }
$lines = Get-Content -LiteralPath $gameLog

# 4. report what the launcher said it used
Log '  --- launcher output ---'
foreach ($l in ($lines | Select-String -Pattern 'Settings:|Using options|options found|scale|fullscreen')) {
    Log ('    ' + $l.Line.Trim())
}

$drv = $lines | Select-String -Pattern 'Driver info: (.+)$' | Select-Object -First 1
if ($drv) { Log ('    GPU: ' + $drv.Matches[0].Groups[1].Value.Split('/')[1].Trim()) }

$panic = $lines | Select-String -Pattern 'panicked' | Select-Object -First 1
Log ('    panic: ' + $(if ($panic) { $panic.Line.Trim() } else { 'none' }))

$fps = $lines | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
    ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
if ($fps.Count -gt 4) {
    $s = $fps[3..($fps.Count - 1)]
    $m = $s | Measure-Object -Average -Minimum -Maximum
    Log ("  RESULT {0}: fps avg={1:N2} min={2:N2} max={3:N2} (n={4})" -f `
        $Tag, $m.Average, $m.Minimum, $m.Maximum, $m.Count)
} else {
    Log "  RESULT ${Tag}: no fps samples (raw=$($fps.Count))"
}

# End-to-end verification: launch through the project's real launcher and confirm
# the framerate, so we test the exact path the user uses rather than invoking
# touchHLE directly.
$ErrorActionPreference = 'Continue'

$root = (Split-Path -Parent $PSScriptRoot)
$log  = Join-Path $root '_analysis\perf\e2e_launcher.log'
$out  = Join-Path $root '_analysis\_e2e.log'

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $out -Value $m -Encoding utf8
}
Set-Content -LiteralPath $out -Value "e2e launcher test $(Get-Date -Format o)" -Encoding utf8

# reference save first, exactly like the documented workflow
& (Join-Path $root 'RestoreTestSave.ps1') -Force *>&1 | ForEach-Object { Log "  $_" }

Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue

# Launch via the launcher script, the same way the .bat wrappers do.
$job = Start-Job -ScriptBlock {
    param($root, $log)
    Set-Location -LiteralPath $root
    & powershell -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $root 'StartZombieFarmNextHour.ps1') -NoSkip *> $log
} -ArgumentList $root, $log

$deadline = (Get-Date).AddSeconds(40)
while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 500 }
if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
Remove-Job $job -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $log)) { Log 'NO LOG PRODUCED'; exit 1 }

$lines = Get-Content -LiteralPath $log
Log '=== launch fingerprint ==='
foreach ($l in ($lines | Select-String -Pattern 'ipa =|sha256 =|Identifier:|Using options|options found')) {
    Log ('  ' + $l.Line.Trim())
}

Log '=== framerate ==='
$fps = $lines | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
    ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
if ($fps.Count -gt 4) {
    $s = $fps[3..($fps.Count - 1)]
    $m = $s | Measure-Object -Average -Minimum -Maximum
    Log ("  EAGL FPS  n={0}  avg={1:N2}  min={2:N2}  max={3:N2}" -f `
        $m.Count, $m.Average, $m.Minimum, $m.Maximum)
} else {
    Log "  no settled samples (raw=$($fps.Count))"
}
$comp = $lines | Select-String -Pattern 'Core Animation compositor FPS: ([0-9.]+)' |
    ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
if ($comp.Count -gt 4) {
    $c = $comp[3..($comp.Count - 1)]
    Log ("  compositor avg={0:N2}" -f ($c | Measure-Object -Average).Average)
}
$panic = $lines | Select-String -Pattern 'panicked' | Select-Object -First 1
Log ("  panic: " + $(if ($panic) { $panic.Line.Trim() } else { 'none' }))

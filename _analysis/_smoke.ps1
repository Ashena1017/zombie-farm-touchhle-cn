# Quick single-run smoke test: how far does a given touchHLE build get with ZFR?
#
# Reports the first panic (if any), whether the app reached "CPU emulation
# begins now", and the FPS samples harvested. Much faster than the full A/B
# script when the goal is just "does it run at all".
param(
    [string]$Exe = "$root\touchHLE_fixed.exe",
    [string[]]$Extra = @(),
    [int]$Seconds = 20,
    [string]$Tag = 'smoke'
)
$ErrorActionPreference = 'Continue'

$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}
$ipa  = Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$out  = Join-Path $root "_analysis\perf\smoke_$Tag.log"
Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

$argv = @($ipa, '--device-family=ipad', '--landscape-right', '--print-fps') + $Extra
Write-Host "=== smoke: $(Split-Path -Leaf $Exe) $($Extra -join ' ') ==="

$job = Start-Job -ScriptBlock {
    param($exe, $argv, $out, $cwd)
    Set-Location -LiteralPath $cwd
    $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
    & $exe @argv *> $out
} -ArgumentList $Exe, $argv, $out, $hleRoot

$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 400 }
if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue; Write-Host "  (stopped after ${Seconds}s)" }
Remove-Job $job -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $out)) { Write-Host '  NO OUTPUT'; exit 0 }
$lines = Get-Content -LiteralPath $out

$began = $lines | Select-String -Pattern 'CPU emulation begins now' | Select-Object -First 1
Write-Host "  reached 'CPU emulation begins': $([bool]$began)"

$panic = $lines | Select-String -Pattern 'panicked at' | Select-Object -First 1
if ($panic) { Write-Host "  PANIC: $($panic.Line.Trim())" }

$reason = $lines | Select-String -Pattern 'assertion failed|Unexpected I/O failure|unimplemented|not implemented' |
    Select-Object -Last 3
foreach ($r in $reason) { Write-Host "  note: $($r.Line.Trim())" }

$fps = $lines | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
    ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
if ($fps.Count -gt 3) {
    $s = $fps[3..($fps.Count - 1)]
    $m = $s | Measure-Object -Average -Minimum -Maximum
    Write-Host ("  EAGL FPS n={0} avg={1:N2} min={2:N2} max={3:N2}" -f $m.Count, $m.Average, $m.Minimum, $m.Maximum)
} else {
    Write-Host "  EAGL FPS: none (raw=$($fps.Count))"
}

$comp = $lines | Select-String -Pattern 'Core Animation compositor FPS: ([0-9.]+)' |
    ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
if ($comp.Count -gt 3) {
    $s2 = $comp[3..($comp.Count - 1)]
    Write-Host ("  compositor avg={0:N2}" -f ($s2 | Measure-Object -Average).Average)
}

Write-Host "  log: $out"

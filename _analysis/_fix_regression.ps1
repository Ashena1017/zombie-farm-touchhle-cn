# Confirm that turning the run-loop fix OFF really reverts Zombie Farm to 30fps.
#
# This is the regression check that matters most for the GUI: the "高速帧率修复"
# dropdown must genuinely control the 30 -> 60fps difference, not merely write a
# token into the options file. A setting that appears to work but does nothing is
# worse than no setting.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$Seconds = 28
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'
$manager = Join-Path $Root 'GameManager.ps1'

function Measure-Run {
    param([string]$Tag, [string]$Spec, [double]$Expect)

    $saved = & powershell -NoProfile -ExecutionPolicy Bypass -File $manager -Set $Spec
    Write-Host "  [$Tag] $saved"

    $gameLog = Join-Path $Root "_analysis\perf\fix_$Tag.log"
    & (Join-Path $Root 'RestoreTestSave.ps1') -Force *>&1 | Out-Null
    Remove-Item -LiteralPath $gameLog -Force -ErrorAction SilentlyContinue

    $job = Start-Job -ScriptBlock {
        param($root, $log)
        Set-Location -LiteralPath $root
        & powershell -NoProfile -ExecutionPolicy Bypass `
            -File (Join-Path $root 'StartZombieFarmNextHour.ps1') -NoSkip *> $log
    } -ArgumentList $Root, $gameLog

    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 500 }
    if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    # Wait for the redirect to finish flushing; reading too early truncates.
    $stable = 0; $last = -1
    while ($stable -lt 4) {
        Start-Sleep -Milliseconds 500
        if (-not (Test-Path -LiteralPath $gameLog)) { continue }
        $size = (Get-Item -LiteralPath $gameLog).Length
        if ($size -eq $last) { $stable++ } else { $stable = 0; $last = $size }
    }

    $lines = Get-Content -LiteralPath $gameLog
    $optLine = ($lines | Select-String -Pattern 'Using options from' | Select-Object -First 1)
    if ($optLine) { Write-Host ('    ' + $optLine.Line.Trim()) }

    # Do not name this $fps if the caller has an $Fps: PowerShell variables are
    # case-insensitive and an array would be coerced to a single string.
    $samples = @($lines | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value })
    if ($samples.Count -le 4) { Write-Host "    no samples (raw=$($samples.Count))"; return $false }

    $s = $samples[3..($samples.Count - 1)]
    $m = $s | Measure-Object -Average -Minimum -Maximum
    $pass = [Math]::Abs($m.Average - $Expect) -lt 2.0
    Write-Host ("    fps avg={0:N2} min={1:N2} max={2:N2} (n={3})  expected ~{4}  {5}" -f `
        $m.Average, $m.Minimum, $m.Maximum, $m.Count, $Expect,
        $(if ($pass) { 'PASS' } else { 'FAIL' })) -ForegroundColor $(if ($pass) { 'Green' } else { 'Red' })
    return $pass
}

Write-Host '=== run-loop fix must actually control the framerate ==='
Write-Host ''

$allOk = $true

# Fix ON, cap 60 -> 60fps
$allOk = (Measure-Run -Tag 'on60' `
    -Spec 'fps_limit=60,scale_hack=1,fullscreen=0,show_fps=1,run_loop_fix=1' `
    -Expect 60) -and $allOk

# Fix OFF, cap 60 -> 30fps (the bug the fix addresses)
$allOk = (Measure-Run -Tag 'off60' `
    -Spec 'fps_limit=60,scale_hack=1,fullscreen=0,show_fps=1,run_loop_fix=0' `
    -Expect 30) -and $allOk

# Fix ON, cap 30 -> 30fps (cap still respected)
$allOk = (Measure-Run -Tag 'on30' `
    -Spec 'fps_limit=30,scale_hack=1,fullscreen=0,show_fps=1,run_loop_fix=1' `
    -Expect 30) -and $allOk

Write-Host ''
if ($allOk) {
    Write-Host 'RESULT: PASS -- the 高速帧率修复 dropdown genuinely controls 30 vs 60 fps' -ForegroundColor Green
    exit 0
} else {
    Write-Host 'RESULT: FAIL -- at least one configuration did not behave as expected' -ForegroundColor Red
    exit 1
}

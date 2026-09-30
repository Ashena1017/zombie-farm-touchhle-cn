# Measure host CPU and GPU cost at 30fps versus 60fps, to answer "is there
# headroom, or is 60fps just trading one bottleneck for another?"
#
# Reports, per configuration:
#   - process CPU as a percentage of ONE logical core (Windows' Process
#     "% Processor Time" sums the threads; 100% == one core fully busy)
#   - total GPU engine utilisation (sum over all engines, all processes)
#   - the touchHLE process's own GPU utilisation, if the counter exposes it
#   - working set
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

$fork = Join-Path $hleRoot 'touchHLE_fork.exe'
$ipa  = Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$log  = Join-Path $root '_analysis\_perf_cost.log'
$restore = Join-Path $root 'RestoreTestSave.ps1'
$fix = '--non-blocking-zero-timeout-run-loop'

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $log -Value $m -Encoding utf8
}
Set-Content -LiteralPath $log -Value "perf cost measurement $(Get-Date -Format o)" -Encoding utf8

function Measure-Run([string]$tag, [string[]]$extra, [int]$seconds) {
    if (Test-Path $restore) { & $restore -Force *>&1 | Out-Null }
    $out = Join-Path $root "_analysis\perf\cost_$tag.log"
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

    $argv = @($ipa, '--device-family=ipad', '--landscape-right', '--print-fps') + $extra
    $job = Start-Job -ScriptBlock {
        param($exe, $argv, $out, $cwd)

        Set-Location -LiteralPath $cwd
        $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
        & $exe @argv *> $out
    } -ArgumentList $fork, $argv, $out, $hleRoot
    # let it boot and reach steady state
    Start-Sleep -Seconds 10
    $proc = Get-Process -Name 'touchHLE_fork' -ErrorAction SilentlyContinue
    if (-not $proc) { Log "  $tag : process not found"; Stop-Job $job -EA SilentlyContinue; Remove-Job $job -Force -EA SilentlyContinue; return }

    $samples = @()
    $gpuSamples = @()
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
        try {
            $c = Get-Counter -Counter "\Process(touchHLE_fork)\% Processor Time" -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop
            $samples += $c.CounterSamples[0].CookedValue
        } catch { }
        try {
            $g = Get-Counter -Counter "\GPU Engine(*)\Utilization Percentage" -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop
            $sum = ($g.CounterSamples | Measure-Object -Property CookedValue -Sum).Sum
            $gpuSamples += $sum
        } catch { }
    }

    $ws = $null
    $p2 = Get-Process -Name 'touchHLE_fork' -ErrorAction SilentlyContinue
    if ($p2) { $ws = [math]::Round($p2.WorkingSet64 / 1MB, 1) }

    if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    $fps = @()
    if (Test-Path $out) {
        $fps = Get-Content $out | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
            ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
        $fps = if ($fps.Count -gt 4) { $fps[3..($fps.Count - 1)] } else { $fps }
    }
    $avgFps = if ($fps.Count) { ($fps | Measure-Object -Average).Average } else { [double]::NaN }
    $cpu = if ($samples.Count) { ($samples | Measure-Object -Average).Average } else { [double]::NaN }
    $gpu = if ($gpuSamples.Count) { ($gpuSamples | Measure-Object -Average).Average } else { [double]::NaN }

    Log ("=== {0} : {1} ===" -f $tag, ($extra -join ' '))
    Log ("  EAGL FPS        {0,8:N2}" -f $avgFps)
    Log ("  CPU (1 core=100%) {0,6:N1} %   [{1} samples]" -f $cpu, $samples.Count)
    Log ("  GPU all engines  {0,7:N1} %   [{1} samples]" -f $gpu, $gpuSamples.Count)
    Log ("  working set      {0,8} MB" -f $ws)
}

Measure-Run 'off30' @() 20
Measure-Run 'on60'  @($fix) 20

Log ''
Log 'CPU is expressed as a percentage of ONE logical core (this machine has 32).'

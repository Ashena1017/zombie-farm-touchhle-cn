# Measure host CPU cost properly, using TotalProcessorTime deltas.
#
# The Get-Counter "\Process(name)\% Processor Time" approach returned 0.0-0.5%,
# which is not credible (an earlier session measured 2-5% of one core). The
# counter's instance naming for this process is unreliable, so measure the
# process's own accumulated CPU time across a fixed wall-clock window instead:
#
#     cpu% of one core = (cpu_seconds_delta / wall_seconds) * 100
#
# Also reports thread count and per-core-normalised load.
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
$log  = Join-Path $root '_analysis\_cpu_cost.log'
$restore = Join-Path $root 'RestoreTestSave.ps1'
$fix = '--non-blocking-zero-timeout-run-loop'

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $log -Value $m -Encoding utf8
}
Set-Content -LiteralPath $log -Value "cpu cost measurement $(Get-Date -Format o)" -Encoding utf8

function Measure-Cpu([string]$tag, [string[]]$extra, [int]$seconds) {
    if (Test-Path $restore) { & $restore -Force *>&1 | Out-Null }
    $out = Join-Path $root "_analysis\perf\cpu_$tag.log"
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

    $argv = @($ipa, '--device-family=ipad', '--landscape-right', '--print-fps') + $extra
    $job = Start-Job -ScriptBlock {
        param($exe, $argv, $out, $cwd)

        Set-Location -LiteralPath $cwd
        $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
        & $exe @argv *> $out
    } -ArgumentList $fork, $argv, $out, $hleRoot
    Start-Sleep -Seconds 10   # boot + reach steady state
    $p = Get-Process -Name 'touchHLE_fork' -ErrorAction SilentlyContinue
    if (-not $p) {
        Log "  $tag : process not found"
        Stop-Job $job -EA SilentlyContinue; Remove-Job $job -Force -EA SilentlyContinue
        return
    }

    $cpu0 = $p.TotalProcessorTime.TotalSeconds
    $t0 = Get-Date
    Start-Sleep -Seconds $seconds
    $p.Refresh()
    $cpu1 = $p.TotalProcessorTime.TotalSeconds
    $wall = ((Get-Date) - $t0).TotalSeconds

    $threads = $p.Threads.Count
    $ws = [math]::Round($p.WorkingSet64 / 1MB, 1)

    if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    $dcpu = $cpu1 - $cpu0
    $pctOfCore = ($dcpu / $wall) * 100
    $logical = [Environment]::ProcessorCount
    $pctOfMachine = $pctOfCore / $logical

    $fps = @()
    if (Test-Path $out) {
        $fps = Get-Content $out | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
            ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
        $fps = if ($fps.Count -gt 4) { $fps[3..($fps.Count - 1)] } else { $fps }
    }
    $avgFps = if ($fps.Count) { ($fps | Measure-Object -Average).Average } else { [double]::NaN }

    Log ("=== {0} : {1} ===" -f $tag, ($extra -join ' '))
    Log ("  EAGL FPS              {0,8:N2}" -f $avgFps)
    Log ("  CPU time consumed     {0,8:N2} s  over {1:N1} s wall" -f $dcpu, $wall)
    Log ("  = {0:N2} % of ONE logical core   ({1:N3} % of all {2} logical cores)" -f `
        $pctOfCore, $pctOfMachine, $logical)
    Log ("  threads {0}   working set {1} MB" -f $threads, $ws)
    Log ("  CPU seconds per frame {0:N6}" -f ($dcpu / [math]::Max($avgFps * $wall, 1)))
}

Measure-Cpu 'off30' @() 25
Measure-Cpu 'on60'  @($fix) 25

Log ''
Log 'If the fix merely removes waiting (rather than adding work), CPU seconds per'
Log 'FRAME should stay roughly constant while frames per second doubles.'

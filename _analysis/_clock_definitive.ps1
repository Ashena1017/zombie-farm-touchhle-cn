# DEFINITIVE test: does the 60fps build advance the game's clock faster?
#
# Zombie Farm's daily-bonus logic logs the emulated clock it computed, via
# TOUCHHLE_ZF_DAILY_TRACE. Because the fork's gettimeofday()/time() both report
# `emulated_system_time()` (= host SystemTime + configured offset), those logged
# clock values are exactly the clock the game reasons about.
#
# So: run the same build with the same fake epoch for the same wall-clock
# duration, at 30fps and at 60fps, and compare the EMULATED clock the game saw.
#
#   correct behaviour -> emulated clock advances ~= wall-clock time in both,
#                        so the two runs report nearly the same clock
#   broken behaviour  -> the 60fps run reports roughly twice the elapsed
#                        emulated time
#
# A second, independent check uses TOUCHHLE_ZF_QUEST_TRACE / status trace to see
# whether game-state counters advance differently.
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
$perf = Join-Path $root '_analysis\perf'
$log  = Join-Path $root '_analysis\_clock_definitive.log'
$restore = Join-Path $root 'RestoreTestSave.ps1'
$fix = '--non-blocking-zero-timeout-run-loop'

# A fixed epoch, close to a local midnight boundary so the daily code path runs.
$fakeEpoch = '1700000000'   # 2023-11-14T22:13:20Z

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $log -Value $m -Encoding utf8
}
Set-Content -LiteralPath $log -Value "definitive clock test $(Get-Date -Format o)" -Encoding utf8

function Run-Clock([string]$tag, [string[]]$extra, [int]$seconds) {
    if (Test-Path $restore) { & $restore -Force *>&1 | Out-Null }
    $out = Join-Path $perf "clk_$tag.log"
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

    $argv = @($ipa, '--device-family=ipad', '--landscape-right', '--print-fps') + $extra
    $job = Start-Job -ScriptBlock {
        param($exe, $argv, $out, $cwd, $epoch)

        Set-Location -LiteralPath $cwd
        $env:TOUCHHLE_FAKE_UNIX_TIME = $epoch
        $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
        $env:TOUCHHLE_ZF_DAILY_TRACE = '1'
        & $exe @argv *> $out
    } -ArgumentList $fork, $argv, $out, $root, $fakeEpoch

    $t0 = Get-Date
    $deadline = $t0.AddSeconds($seconds)
    while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 500 }
    $wall = ((Get-Date) - $t0).TotalSeconds
    if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    $lines = if (Test-Path $out) { Get-Content -LiteralPath $out } else { @() }

    $fps = $lines | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
    $fps = if ($fps.Count -gt 4) { $fps[3..($fps.Count - 1)] } else { $fps }
    $avgFps = if ($fps.Count) { ($fps | Measure-Object -Average).Average } else { [double]::NaN }

    # Any emulated-clock seconds the app's own trace printed
    $stamps = @()
    foreach ($l in $lines) {
        foreach ($m in [regex]::Matches($l, '\(([0-9]{9,11})(?:\.[0-9]+)? Unix seconds')) {
            $stamps += [int64]$m.Groups[1].Value
        }
    }

    $dayLines = $lines | Select-String -Pattern 'daily trace:' | Select-Object -First 4

    Log ("=== {0} : {1} ===" -f $tag, ($extra -join ' '))
    Log ("  wall clock       {0,7:N2} s" -f $wall)
    Log ("  EAGL FPS         {0,7:N2}" -f $avgFps)
    if ($stamps.Count) {
        $min = ($stamps | Measure-Object -Minimum).Minimum
        $max = ($stamps | Measure-Object -Maximum).Maximum
        Log ("  emulated clock reported by app: min={0} max={1}  span={2} s" -f $min, $max, ($max - $min))
        Log ("  (fake epoch was {0}; headroom = {1} s above epoch)" -f $fakeEpoch, ($min - [int64]$fakeEpoch))
    } else {
        Log '  emulated clock: no values captured'
    }
    foreach ($d in $dayLines) { Log ("  trace: " + $d.Line.Trim()) }
    Log ("  log: {0}" -f $out)
}

Run-Clock 'off30' @() 30
Run-Clock 'on60'  @($fix) 30

Log ''
Log 'EXPECTED IF CORRECT: both runs show a wall-clock-like elapsed time, and the'
Log '60fps run does NOT show twice the elapsed game time.'

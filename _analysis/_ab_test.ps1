# A/B framerate test for the zero-timeout run-loop fix.
#
# Runs the SAME app and the SAME save under three configurations and records the
# FPS lines touchHLE prints, so the comparison is apples-to-apples:
#   A. stock (upstream behaviour)          -- just the IPA
#   B. fixed exe, option off (control)     -- proves the option is what matters
#   C. fixed exe, option on (the fix)
#
# Each run is time-boxed and killed, because touchHLE is interactive.
$ErrorActionPreference = 'Continue'

$root  = (Split-Path -Parent $PSScriptRoot)

# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

$log   = Join-Path $root '_analysis\_ab_test.log'
$perf  = Join-Path $root '_analysis\perf'
$stock = Join-Path $hleRoot 'touchHLE.exe'
$fixed = Join-Path $hleRoot 'touchHLE_fixed.exe'
$ipa   = Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}
Set-Content -LiteralPath $log -Value "A/B test started $(Get-Date -Format o)" -Encoding utf8

foreach ($p in @($stock, $fixed, $ipa)) {
    if (-not (Test-Path $p)) { Log "MISSING: $p"; exit 1 }
    Log "ok: $p  ($((Get-Item $p).Length) bytes)"
}

# Put the reference save in place, like the project's own workflow does, so all
# three cases start from identical game state.
$restore = Join-Path $root 'RestoreTestSave.ps1'
if (Test-Path $restore) {
    Log 'restoring reference save ...'
    & $restore -Force *>&1 | ForEach-Object { Log "  | $_" }
}

function Run-Case([string]$tag, [string]$exe, [string[]]$extra, [int]$seconds) {
    $out = Join-Path $perf "ab_$tag.log"
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
    Log "=== case $tag : $([IO.Path]::GetFileName($exe)) $($extra -join ' ') ==="

    $argv = @($ipa, '--device-family=ipad', '--landscape-right', '--print-fps') + $extra
    # NOTE: touchHLE resolves touchHLE_dylibs/ and touchHLE_fonts/ relative to
    # the CURRENT DIRECTORY, and Start-Job does not inherit ours, so the job
    # must cd into the project root itself (otherwise it panics in fs.rs with
    # "touchHLE_dylibs/libz.1.2.3.dylib ... os error 3").
    #
    # The user's real launcher (StartZombieFarmNextHour.ps1) runs touchHLE.exe
    # from the project root, which is why the vendor DLLs are found there.
    #
    # GPU NOTE: this machine has both an RTX 4080 and an Intel iGPU, and which
    # one SDL picks is not deterministic -- one run above got "Intel(R)
    # RaptorLake-S Mobile Graphics Controller" and another got the NVIDIA. That
    # would confound an A/B measurement, so every case here is run the same way
    # and the driver line is recorded for each, letting us check afterwards.
    $job = Start-Job -ScriptBlock {
        param($exe, $argv, $out, $cwd)

        Set-Location -LiteralPath $cwd
        $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
        & $exe @argv *> $out
    } -ArgumentList $exe, $argv, $out, $hleRoot
    # let it boot and settle, then measure
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') {
        Start-Sleep -Milliseconds 500
    }
    if ($job.State -eq 'Running') {
        Stop-Job $job -ErrorAction SilentlyContinue
        Log "  (stopped after ${seconds}s)"
    }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    # harvest FPS samples
    if (-not (Test-Path $out)) { Log "  NO OUTPUT FILE"; return }
    $driver = Get-Content -LiteralPath $out -ErrorAction SilentlyContinue |
        Select-String -Pattern 'Driver info: (.+)$' | Select-Object -First 1
    if ($driver) { Log "  driver: $($driver.Matches[0].Groups[1].Value.Trim())" }
    $panic = Get-Content -LiteralPath $out -ErrorAction SilentlyContinue |
        Select-String -Pattern "panicked at" | Select-Object -First 1
    if ($panic) { Log "  PANIC: $($panic.Line.Trim())" }

    $fps = Get-Content -LiteralPath $out -ErrorAction SilentlyContinue |
        Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
    $comp = Get-Content -LiteralPath $out -ErrorAction SilentlyContinue |
        Select-String -Pattern 'Core Animation compositor FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value }

    # drop the first 3 samples (startup ramp)
    $fpsSettled = if ($fps.Count -gt 3) { $fps[3..($fps.Count - 1)] } else { $fps }
    $compSettled = if ($comp.Count -gt 3) { $comp[3..($comp.Count - 1)] } else { $comp }

    if ($fpsSettled.Count -gt 0) {
        $m = ($fpsSettled | Measure-Object -Average -Minimum -Maximum)
        Log ("  EAGL FPS  n={0}  avg={1:N2}  min={2:N2}  max={3:N2}" -f `
            $m.Count, $m.Average, $m.Minimum, $m.Maximum)
    } else { Log "  EAGL FPS: no settled samples (raw=$($fps.Count))" }

    if ($compSettled.Count -gt 0) {
        $m2 = ($compSettled | Measure-Object -Average -Minimum -Maximum)
        Log ("  compositor n={0}  avg={1:N2}" -f $m2.Count, $m2.Average)
    }
    Log "  log: $out"
}

# A: stock binary, no extra options
Run-Case 'stock' $stock @() 55
# B: fixed binary, option OFF (should match stock)
Run-Case 'fixed_off' $fixed @() 55
# C: fixed binary, option ON (should be ~2x)
Run-Case 'fixed_on' $fixed @('--non-blocking-zero-timeout-run-loop') 55

Log '--- summary ---'
foreach ($tag in 'stock','fixed_off','fixed_on') {
    $f = Join-Path $perf "ab_$tag.log"
    if (-not (Test-Path $f)) { Log "  $tag : no log"; continue }
    $fps = Get-Content -LiteralPath $f | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
    $s = if ($fps.Count -gt 3) { $fps[3..($fps.Count - 1)] } else { $fps }
    if ($s.Count -gt 0) {
        Log ("  {0,-10} avg={1:N2}  n={2}" -f $tag, ($s | Measure-Object -Average).Average, $s.Count)
    } else { Log "  {0,-10} no samples" -f $tag }
}
Log 'A/B test DONE'

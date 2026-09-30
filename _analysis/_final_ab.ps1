# Final A/B/C comparison of the three binaries, plus a longer 60fps stability run.
#
#   A. touchHLE.exe            the user's existing ZFR-adapted build (control)
#   B. touchHLE_fork.exe       fork source rebuilt + run-loop fix, option OFF
#   C. touchHLE_fork.exe       fork source rebuilt + run-loop fix, option ON
#
# B exists to prove that the rebuilt binary behaves identically to the known-good
# A when the new option is off, i.e. that the rebuild itself changed nothing.
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

$log  = Join-Path $root '_analysis\_final_ab.log'
$perf = Join-Path $root '_analysis\perf'
$stock = Join-Path $hleRoot 'touchHLE.exe'
$fork  = Join-Path $hleRoot 'touchHLE_fork.exe'
$ipa   = Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$restore = Join-Path $root 'RestoreTestSave.ps1'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}
Set-Content -LiteralPath $log -Value "final A/B started $(Get-Date -Format o)" -Encoding utf8

function Run-Case([string]$tag, [string]$exe, [string[]]$extra, [int]$seconds) {
    $out = Join-Path $perf "fin_$tag.log"
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

    if (Test-Path $restore) { & $restore -Force *>&1 | Out-Null }
    Log "=== $tag : $(Split-Path -Leaf $exe) $($extra -join ' ') ==="

    $argv = @($ipa, '--device-family=ipad', '--landscape-right', '--print-fps') + $extra
    $job = Start-Job -ScriptBlock {
        param($exe, $argv, $out, $cwd)

        Set-Location -LiteralPath $cwd
        $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
        & $exe @argv *> $out
    } -ArgumentList $exe, $argv, $out, $hleRoot
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 500 }
    if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $out)) { Log '  NO OUTPUT'; return }
    $lines = Get-Content -LiteralPath $out

    $drv = $lines | Select-String -Pattern 'Driver info: (.+)$' | Select-Object -First 1
    if ($drv) {
        $d = $drv.Matches[0].Groups[1].Value
        $which = if ($d -match 'NVIDIA') { 'NVIDIA RTX 4080' } elseif ($d -match 'Intel') { 'Intel iGPU' } else { '?' }
        Log "  GPU: $which"
    }
    $panic = $lines | Select-String -Pattern 'panicked at' | Select-Object -First 1
    if ($panic) { Log "  PANIC: $($panic.Line.Trim())" }

    $fps = $lines | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
    if ($fps.Count -gt 4) {
        $s = $fps[3..($fps.Count - 1)]
        $m = $s | Measure-Object -Average -Minimum -Maximum
        # frame-time consistency: how far samples stray from the mean
        $sd = [math]::Sqrt((($s | ForEach-Object { ($_ - $m.Average) * ($_ - $m.Average) } |
              Measure-Object -Sum).Sum) / $s.Count)
        Log ("  EAGL FPS  n={0}  avg={1:N2}  min={2:N2}  max={3:N2}  sd={4:N3}" -f `
            $m.Count, $m.Average, $m.Minimum, $m.Maximum, $sd)
    } else { Log "  EAGL FPS: none (raw=$($fps.Count))" }

    $comp = $lines | Select-String -Pattern 'Core Animation compositor FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
    if ($comp.Count -gt 4) {
        $c = $comp[3..($comp.Count - 1)]
        Log ("  compositor avg={0:N2}" -f ($c | Measure-Object -Average).Average)
    }
    Log "  log: $out"
}

Run-Case 'A_stock'    $stock @() 45
Run-Case 'B_fork_off' $fork  @() 45
Run-Case 'C_fork_on'  $fork  @('--non-blocking-zero-timeout-run-loop') 45
# longer run to check 60fps holds up
Run-Case 'D_fork_on_long' $fork @('--non-blocking-zero-timeout-run-loop') 90

Log '--- summary ---'
Log ("{0,-16} {1,>8} {2,>8} {3,>8}" -f 'case', 'avg', 'min', 'max')
foreach ($tag in 'A_stock', 'B_fork_off', 'C_fork_on', 'D_fork_on_long') {
    $f = Join-Path $perf "fin_$tag.log"
    if (-not (Test-Path $f)) { Log ("{0,-16} no log" -f $tag); continue }
    $fps = Get-Content -LiteralPath $f | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
        ForEach-Object { [double]$_.Matches[0].Groups[1].Value }
    if ($fps.Count -gt 4) {
        $s = $fps[3..($fps.Count - 1)]
        $m = $s | Measure-Object -Average -Minimum -Maximum
        Log ("{0,-16} {1,8:N2} {2,8:N2} {3,8:N2}" -f $tag, $m.Average, $m.Minimum, $m.Maximum)
    } else { Log ("{0,-16} no samples" -f $tag) }
}
Log 'final A/B DONE'

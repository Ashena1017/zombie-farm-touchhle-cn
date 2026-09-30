# Compare run-loop service rate and per-frame cost at 30fps vs 60fps.
#
# The key question: raising the framerate must NOT change how often the run loop
# is serviced, because that is what drives timers, run-loop sources and touch
# input. The fix removes ONE of the two zero-timeout polls the app makes per
# frame, so:
#
#     30fps x 2 polls = 60 services/second
#     60fps x 1 poll  = 60 services/second      <-- unchanged
#
# The fork's own --zfr-profile gives cumulative counters, so we can check this
# directly instead of arguing about it.
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
$log  = Join-Path $root '_analysis\_runloop_rate.log'
$restore = Join-Path $root 'RestoreTestSave.ps1'

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $log -Value $m -Encoding utf8
}
Set-Content -LiteralPath $log -Value "run-loop rate check $(Get-Date -Format o)" -Encoding utf8

function Run-Profile([string]$tag, [string[]]$extra, [int]$seconds) {
    $out = Join-Path $perf "rl_$tag.log"
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
    if (Test-Path $restore) { & $restore -Force *>&1 | Out-Null }

    $argv = @($ipa, '--device-family=ipad', '--landscape-right', '--zfr-profile') + $extra
    $job = Start-Job -ScriptBlock {
        param($exe, $argv, $out, $cwd)

        Set-Location -LiteralPath $cwd
        $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
        & $exe @argv *> $out
    } -ArgumentList $fork, $argv, $out, $hleRoot
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 500 }
    if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $out)) { Log "  $tag : NO OUTPUT"; return }

    # The profile prints a periodic block; take the LAST one (largest elapsed).
    $lines = Get-Content -LiteralPath $out
    $elapsed = $null
    foreach ($l in $lines) {
        if ($l -match 'periodic,\s*([0-9.]+)s elapsed') { $elapsed = [double]$Matches[1] }
    }
    $counters = @{}
    foreach ($name in 'run_loop', 'eagl_present_renderbuffer', 'guest_cpu_run',
                      'objc_imp_call', 'environment_run_inner') {
        # last line starting with the counter name: name calls samples total delta avg
        $hits = $lines | Where-Object { $_ -match "^\s*$([regex]::Escape($name))\s" }
        if ($hits) {
            $f = ($hits[-1] -split '\s+') | Where-Object { $_ -ne '' }
            $counters[$name] = [int]$f[1]
        }
    }

    Log ("=== {0} : {1} ===" -f $tag, ($extra -join ' '))
    if ($null -eq $elapsed) { Log '  (no elapsed marker)'; return }
    Log ("  elapsed {0:N1}s" -f $elapsed)
    foreach ($k in 'run_loop', 'eagl_present_renderbuffer', 'guest_cpu_run', 'objc_imp_call') {
        if ($counters.ContainsKey($k)) {
            $rate = $counters[$k] / $elapsed
            Log ("  {0,-28} {1,8} calls   {2,7:N2}/s" -f $k, $counters[$k], $rate)
        }
    }
    if ($counters.ContainsKey('run_loop') -and $counters.ContainsKey('eagl_present_renderbuffer') -and
        $counters['eagl_present_renderbuffer'] -gt 0) {
        $ratio = $counters['run_loop'] / $counters['eagl_present_renderbuffer']
        Log ("  run_loop / present ratio  = {0:N4}" -f $ratio)
    }
}

Run-Profile 'off30' @() 40
Run-Profile 'on60'  @('--non-blocking-zero-timeout-run-loop') 40

Log ''
Log 'expected: run_loop ~= 60/s in BOTH cases; present ~= 30/s vs ~= 60/s;'
Log '          ratio ~= 2.0 with the fix off, ~= 1.0 with it on.'

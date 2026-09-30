# Functional equivalence check: does the rebuilt fork behave like the user's
# existing binary apart from the framerate?
#
# The project's whole point is the Chinese-localisation patches, so "it renders
# at 60fps" is not sufficient -- the game's own code paths must still run. This
# compares the app's own stdout and touchHLE's warnings between:
#
#   A. touchHLE.exe        (the user's known-good binary)
#   B. touchHLE_fork.exe   (rebuilt, option OFF)
#   C. touchHLE_fork.exe   (rebuilt, option ON, i.e. 60fps)
#
# B is the important one: it isolates "did rebuilding change anything?" from
# "did the new option change anything?".
$ErrorActionPreference = 'Continue'

$root = (Split-Path -Parent $PSScriptRoot)
$ipa  = Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$perf = Join-Path $root '_analysis\perf'
$log  = Join-Path $root '_analysis\_equiv.log'
$restore = Join-Path $root 'RestoreTestSave.ps1'
$fix = '--non-blocking-zero-timeout-run-loop'

function Log([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $log -Value $m -Encoding utf8
}
Set-Content -LiteralPath $log -Value "equivalence check $(Get-Date -Format o)" -Encoding utf8

function Capture([string]$tag, [string]$exe, [string[]]$extra, [int]$seconds) {
    if (Test-Path $restore) { & $restore -Force *>&1 | Out-Null }
    $out = Join-Path $perf "eq_$tag.log"
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
    $argv = @($ipa, '--device-family=ipad', '--landscape-right') + $extra
    $job = Start-Job -ScriptBlock {
        param($exe, $argv, $out, $cwd)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

        Set-Location -LiteralPath $cwd
        $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
        & $exe @argv *> $out
    } -ArgumentList $exe, $argv, $out, $hleRoot
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline -and $job.State -eq 'Running') { Start-Sleep -Milliseconds 500 }
    if ($job.State -eq 'Running') { Stop-Job $job -ErrorAction SilentlyContinue }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    return $out
}

function Summarise([string]$tag, [string]$file) {
    if (-not (Test-Path $file)) { Log "  $tag : NO LOG"; return $null }
    $lines = Get-Content -LiteralPath $file
    $app = $lines | Where-Object { $_ -match '^ZFR\[0\]' }
    $warn = $lines | Where-Object { $_ -match 'Warning:|TODO:|panicked' }
    # normalise: strip addresses, numbers, paths so runs are comparable
    $norm = {
        param($s)
        $s = $s -replace '0x[0-9a-f]+', '0xADDR'
        $s = $s -replace '\d+\.\d+', 'N'
        $s = $s -replace '\b\d+\b', 'N'
        $s -replace '\\', '/'
    }
    $appSet = $app | ForEach-Object { & $norm $_ } | Sort-Object -Unique
    $warnSet = $warn | ForEach-Object { & $norm $_ } | Sort-Object -Unique
    Log ("=== {0} ===" -f $tag)
    Log ("  app stdout lines : {0}  ({1} distinct)" -f $app.Count, $appSet.Count)
    Log ("  warning/TODO lines: {0}  ({1} distinct)" -f $warn.Count, $warnSet.Count)
    $panic = $lines | Where-Object { $_ -match 'panicked' }
    Log ("  panics            : {0}" -f $panic.Count)
    return [pscustomobject]@{ App = $appSet; Warn = $warnSet; File = $file }
}

$a = Summarise 'A_stock'    (Capture 'A' (Join-Path $hleRoot 'touchHLE.exe')      @() 20)
$b = Summarise 'B_fork_off' (Capture 'B' (Join-Path $hleRoot 'touchHLE_fork.exe') @() 20)
$c = Summarise 'C_fork_on'  (Capture 'C' (Join-Path $hleRoot 'touchHLE_fork.exe') @($fix) 20)

Log ''
Log '--- differences in app stdout (A vs B: rebuild effect) ---'
$d = Compare-Object $a.App $b.App
if ($d) { $d | ForEach-Object { Log ("  {0} {1}" -f $_.SideIndicator, $_.InputObject) } }
else { Log '  (identical)' }

Log ''
Log '--- differences in app stdout (B vs C: option effect) ---'
$d2 = Compare-Object $b.App $c.App
if ($d2) { $d2 | ForEach-Object { Log ("  {0} {1}" -f $_.SideIndicator, $_.InputObject) } }
else { Log '  (identical)' }

Log ''
Log '--- differences in warnings (A vs B) ---'
$d3 = Compare-Object $a.Warn $b.Warn
if ($d3) { $d3 | Select-Object -First 30 | ForEach-Object { Log ("  {0} {1}" -f $_.SideIndicator, $_.InputObject) } }
else { Log '  (identical)' }

Log ''
Log '--- differences in warnings (B vs C) ---'
$d4 = Compare-Object $b.Warn $c.Warn
if ($d4) { $d4 | Select-Object -First 30 | ForEach-Object { Log ("  {0} {1}" -f $_.SideIndicator, $_.InputObject) } }
else { Log '  (identical)' }

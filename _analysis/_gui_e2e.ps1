# End-to-end: change settings through GameManager.ps1's own -Set path, launch via
# the real launcher, and confirm the game runs at the configured framerate.
#
# This matters because the settings mechanism changed: they now live in
# touchHLE_options.txt (touchHLE's own per-app file) rather than being passed on
# the command line, so it must be shown that touchHLE actually reads that line.
# A passing -SelfTest only proves the file is written correctly.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Tag = 'e2e',
    [string]$Fps = '60',
    [int]$Scale = 1,
    [int]$Seconds = 32,
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'
$gameLog = Join-Path $Root "_analysis\perf\gui_e2e_$Tag.log"
$manager = Join-Path $Root 'GameManager.ps1'

# --- write options through the GUI's own code -------------------------------
$spec = "fps_limit=$Fps,scale_hack=$Scale,fullscreen=0,show_fps=1,run_loop_fix=1"
$saved = & powershell -NoProfile -ExecutionPolicy Bypass -File $manager -Set $spec
Write-Host "  $saved"

$line = (& powershell -NoProfile -ExecutionPolicy Bypass -File $manager -ShowSettings) -join '  '
Write-Host "  readback     : $line"

# --- launch through the real launcher --------------------------------------
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

# Stop-Job returns before the spawned powershell.exe has finished flushing its
# redirected output, so reading immediately yields a truncated log (this was
# observed as "raw=1 sample"). Wait for the game process to go away and for the
# file size to stop changing before parsing.
Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

$stableFor = 0
$lastSize = -1
while ($stableFor -lt 4) {
    Start-Sleep -Milliseconds 500
    if (-not (Test-Path -LiteralPath $gameLog)) { continue }
    $size = (Get-Item -LiteralPath $gameLog).Length
    if ($size -eq $lastSize) { $stableFor++ } else { $stableFor = 0; $lastSize = $size }
}

if (-not (Test-Path $gameLog)) { Write-Host '  NO LOG'; exit 1 }
$logLines = Get-Content -LiteralPath $gameLog
Write-Host ("  log: {0} lines, {1} bytes" -f $logLines.Count, $lastSize)

# touchHLE says which options it applied, which proves it read our line.
foreach ($l in ($logLines | Select-String -Pattern 'Using options from|No options found')) {
    Write-Host ('  ' + $l.Line.Trim())
}
$panic = $logLines | Select-String -Pattern 'panicked' | Select-Object -First 1
Write-Host ('  panic: ' + $(if ($panic) { $panic.Line.Trim() } else { 'none' }))

# NOTE: do NOT name this $fps. PowerShell variable names are case-insensitive, so
# $fps and the [string]$Fps parameter are the same variable, and assigning an
# array to it coerces the array into one space-joined string -- making .Count
# report 1 no matter how many samples were parsed.
$fpsSamples = @($logLines | Select-String -Pattern 'EAGLContext .* FPS: ([0-9.]+)' |
    ForEach-Object { [double]$_.Matches[0].Groups[1].Value })

if ($fpsSamples.Count -gt 4) {
    $s = $fpsSamples[3..($fpsSamples.Count - 1)]
    $m = $s | Measure-Object -Average -Minimum -Maximum
    Write-Host ("  RESULT [{0}]: fps avg={1:N2} min={2:N2} max={3:N2} (n={4})" -f `
        $Tag, $m.Average, $m.Minimum, $m.Maximum, $m.Count)

    $want = 0.0
    if ([double]::TryParse($Fps, [ref]$want) -and [Math]::Abs($m.Average - $want) -lt 2.0) {
        Write-Host '  => PASS: touchHLE_options.txt reached the game' -ForegroundColor Green
    } else {
        Write-Host "  => FAIL: expected ~$want, got $($m.Average)" -ForegroundColor Red
    }
} else {
    Write-Host "  no fps samples (raw=$($fpsSamples.Count))"
}

# The options line must still be exactly what we asked for.
$final = (& powershell -NoProfile -ExecutionPolicy Bypass -File $manager -ShowSettings) -join ' '
Write-Host "  final        : $final"

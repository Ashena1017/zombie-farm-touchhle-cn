param(
    [int]$Hours = 0,
    [int]$Minutes = 0,
    [switch]$Reset,
    [switch]$NoSkip,
    [switch]$Interactive,

    # Launch without any console window and capture touchHLE's output to stdout
    # instead of a console. Used by the 游戏管理 GUI, which is a GUI-subsystem
    # process and must not cause a console to be allocated.
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

$offsetFile = Join-Path $hleRoot 'touchHLE_time_offset_seconds.txt'
$game = Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v27fix.ipa'
$touchHLE = Join-Path $hleRoot 'touchHLE.exe'

if ($Reset) {
    if ($NoSkip) {
        throw 'Reset cannot be combined with NoSkip.'
    }
    Remove-Item -LiteralPath $offsetFile -Force -ErrorAction SilentlyContinue
}

if ($Interactive) {
    if ($NoSkip -or $Reset) {
        throw 'Interactive cannot be combined with NoSkip or Reset.'
    }

    do {
        $duration = (Read-Host 'Enter skip time as HH:MM (for example 6:15 or 0:30)').Trim()
        $validDuration = $duration -match '^([0-9]+):([0-9]{1,2})$'
        if ($validDuration) {
            try {
                $Hours = [int]$Matches[1]
                $Minutes = [int]$Matches[2]
                $validDuration = $Minutes -le 59 -and ($Hours -gt 0 -or $Minutes -gt 0)
            } catch {
                $validDuration = $false
            }
        }
        if (-not $validDuration) {
            Write-Host 'Invalid format. Use non-negative hours and minutes from 00 to 59, for example 6:15.'
        }
    } while (-not $validDuration)
}

if (-not $NoSkip -and $Hours -lt 0) {
    throw 'Hours cannot be negative.'
}

if (-not $NoSkip -and ($Minutes -lt 0 -or $Minutes -gt 59)) {
    throw 'Minutes must be between 0 and 59.'
}

[int64]$increment = 0
if (-not $NoSkip) {
    $increment = ([int64]$Hours * 3600) + ([int64]$Minutes * 60)
}
if (-not $NoSkip -and $increment -le 0) {
    throw 'The time increment must be greater than zero.'
}

if (-not (Test-Path -LiteralPath $touchHLE)) {
    throw "touchHLE.exe not found: $touchHLE"
}

if (-not (Test-Path -LiteralPath $game)) {
    throw "Game IPA not found: $game"
}

# Diagnostic fingerprint: record exactly which IPA build was launched, so the
# analysis side can prove which executable actually ran.
$fingerprint = Join-Path $hleRoot 'zfr_last_launch.txt'
@(
    "ipa = $(Split-Path -Leaf $game)"
    "sha256 = $((Get-FileHash -LiteralPath $game -Algorithm SHA256).Hash)"
    "launched = $(Get-Date -Format o)"
) | Set-Content -LiteralPath $fingerprint -Encoding utf8

[int64]$offset = 0
if (Test-Path -LiteralPath $offsetFile) {
    $saved = (Get-Content -LiteralPath $offsetFile -Raw).Trim()
    if ($saved -and -not [int64]::TryParse($saved, [ref]$offset)) {
        throw "Invalid offset file: $offsetFile"
    }
}

if ($offset -lt 0 -or $increment -gt ([int64]::MaxValue - $offset)) {
    throw 'The cumulative time offset would exceed the Int64 range. Use -Reset to start a new offset.'
}

if (-not $NoSkip) {
    $offset += $increment
    [System.IO.File]::WriteAllText($offsetFile, [string]$offset)
}
$env:TOUCHHLE_TIME_OFFSET_SECONDS = [string]$offset

if ($NoSkip) {
    Write-Host "Starting Zombie Farm without advancing time; keeping cumulative offset at $offset seconds."
} else {
    $totalHours = [math]::Floor($increment / 3600)
    $totalMinutes = [int](($increment % 3600) / 60)
    Write-Host "Starting Zombie Farm with increment ${totalHours}h ${totalMinutes}m; cumulative offset is $offset seconds."
}

# Display and framerate options (device size, window scale, framerate, fullscreen,
# and the 60fps run-loop fix) are deliberately NOT passed here. They live in
# touchHLE_options.txt on the com.playforge.ZombieFarm.ZFR line, which the
# 游戏管理 UI edits. Keeping them there means they also apply when touchHLE is
# started by some other route, and there is exactly one place to look when
# something looks wrong.
#
# Note that --device-family used to be hardcoded here as "ipad". It is not any
# more, because command-line options OVERRIDE touchHLE_options.txt (lib.rs applies
# them last), so leaving it here would silently defeat the UI's device-size
# setting. The options file now always specifies it, and the UI writes it.
$touchHLEArgs = @($game, '--landscape-right')

if ($Quiet) {
    # Called from the GUI. touchHLE.exe is a console-subsystem program, so if we
    # launched it with `&` from a process that has no console, Windows would
    # allocate a brand-new console window for it -- exactly the black window the
    # GUI exists to avoid. CreateNoWindow suppresses that, and its output is
    # captured to a log instead of being shown.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $touchHLE
    $psi.Arguments = ($touchHLEArgs | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
    $psi.WorkingDirectory = $root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $proc = [System.Diagnostics.Process]::Start($psi)
    # Drain both pipes at once; reading them sequentially can deadlock when the
    # child fills the second pipe's buffer while we are blocked on the first.
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    $captured = ''
    try { $captured += $outTask.Result } catch { }
    try { $captured += $errTask.Result } catch { }

    if ($captured) { Write-Output $captured }
    exit $proc.ExitCode
}

& $touchHLE @touchHLEArgs
exit $LASTEXITCODE

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
$paths = & (Join-Path $PSScriptRoot 'RepositoryPaths.ps1')
$hleRoot = $paths.Emulator
$env:PATH = "$PSScriptRoot;$env:PATH"

$offsetFile = Join-Path $hleRoot 'touchHLE_time_offset_seconds.txt'
$game = Join-Path $paths.Ipa 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa'
$touchHLE = Join-Path $hleRoot 'touchHLE.exe'

if ($Reset -and $NoSkip) {
    throw 'Reset cannot be combined with NoSkip.'
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

[int64]$offset = 0
if (-not $Reset -and (Test-Path -LiteralPath $offsetFile)) {
    $saved = [System.IO.File]::ReadAllText($offsetFile).Trim()
    if ($saved -and -not [int64]::TryParse($saved, [ref]$offset)) {
        throw "Invalid offset file: $offsetFile"
    }
}

[int64]$base = 0
if (-not [int64]::TryParse($env:TOUCHHLE_FAKE_UNIX_TIME, [ref]$base)) {
    $base = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
}
$target = [decimal]$base + $offset + $increment
if ($offset -lt 0 -or $increment -gt ([int64]::MaxValue - $offset) -or
    $target -lt 0 -or $target -gt [int]::MaxValue) {
    throw 'The cumulative time offset would exceed the range supported by the game. Use -Reset to start a new offset.'
}
$offset += $increment

# Diagnostic fingerprint: record exactly which IPA build was launched, so the
# analysis side can prove which executable actually ran.
$fingerprint = Join-Path $hleRoot 'zfr_last_launch.txt'
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $ipaStream = [System.IO.File]::OpenRead($game)
    try {
        $ipaHash = [BitConverter]::ToString($sha256.ComputeHash($ipaStream)).Replace('-', '')
    } finally {
        $ipaStream.Dispose()
    }
} finally {
    $sha256.Dispose()
}
@(
    "ipa = $(Split-Path -Leaf $game)"
    "sha256 = $ipaHash"
    "launched = $(Get-Date -Format o)"
) | Set-Content -LiteralPath $fingerprint -Encoding utf8

if (-not $NoSkip) {
    $tempFile = Join-Path $hleRoot ('.time-offset-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    try {
        [System.IO.File]::WriteAllText($tempFile, [string]$offset)
        if (Test-Path -LiteralPath $offsetFile -PathType Leaf) {
            [System.IO.File]::Replace($tempFile, $offsetFile, [NullString]::Value)
        } else {
            [System.IO.File]::Move($tempFile, $offsetFile)
        }
    } finally {
        [System.IO.File]::Delete($tempFile)
    }
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
    $psi.WorkingDirectory = $hleRoot
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

Push-Location -LiteralPath $hleRoot
try {
    & $touchHLE @touchHLEArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

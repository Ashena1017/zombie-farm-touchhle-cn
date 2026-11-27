param(
    [int]$Hours = 0,
    [int]$Minutes = 0,
    [switch]$Reset,
    [switch]$NoSkip,
    [switch]$Interactive,

    # Capture both output streams without opening a console for the child.
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$paths = & (Join-Path $PSScriptRoot 'RepositoryPaths.ps1')
$hleRoot = $paths.Emulator
$env:PATH = "$PSScriptRoot;$env:PATH"

. (Join-Path $PSScriptRoot 'GameManager.ps1') -CoreOnly
$releaseInfo = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'release.json') | ConvertFrom-Json
$game = Join-Path $paths.Ipa $releaseInfo.ipa.name
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

$info = Read-IpaInfo -Path $game
if (-not $info.AppId) { throw $info.Error }
Set-CurrentIpa $info
$launchPaths = Get-LaunchPaths

# Display and framerate options come from touchHLE_options.txt, as in the manager.
$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $touchHLE
$psi.Arguments = '"' + $game + '"'
$psi.WorkingDirectory = $hleRoot
$psi.UseShellExecute = $false
if ($Quiet) {
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
}

$proc = Start-GameWithTimeOffset -StartInfo $psi -Paths $launchPaths -SkipSeconds $increment -Reset:$Reset
try {
    $offset = $psi.EnvironmentVariables['TOUCHHLE_TIME_OFFSET_SECONDS']
    if ($NoSkip) {
        Write-Host "Starting Zombie Farm without advancing time; keeping cumulative offset at $offset seconds."
    } else {
        Write-Host "Starting Zombie Farm with increment ${Hours}h ${Minutes}m; cumulative offset is $offset seconds."
    }

    if ($Quiet) {
        # Start reading both pipes before waiting so either pipe can fill independently.
        $stdout = $proc.StandardOutput.ReadToEndAsync()
        $stderr = $proc.StandardError.ReadToEndAsync()
    }
    $proc.WaitForExit()
    if ($Quiet) {
        $captured = $stdout.Result + $stderr.Result
        if ($captured) { Write-Output $captured }
    }
    $code = $proc.ExitCode
} finally { $proc.Dispose() }
exit $code

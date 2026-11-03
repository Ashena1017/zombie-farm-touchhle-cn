# Cross-check the fingerprints pinned in GameManager.ps1 against the files that
# are about to be packaged.
#
# Why this exists: the manager paints itself red when touchHLE.exe or the bundled
# IPA does not match $script:PinnedExeSha256 / $script:PinnedIpaSha256, and
# touchHLE refuses to start a mismatched IPA at all (src/zfr_integrity.rs). Those
# constants are maintained by hand, one line each. Forget to update one after a
# rebuild and the release ships a bundle that argues with itself: every player
# sees a red 文件校验 line, and the game will not start.
#
# So _build_release.ps1 runs this first and stops if anything disagrees. It is
# also usable on its own:
#
#   _analysis\_check_pinned_hashes.ps1 -ManagerPath GameManager.ps1 `
#       -ExePath touchHLE\touchHLE.exe -IpaPath 'zombie_farm_ipa\....ipa'
#
# Exit code 0 = all pinned values match, 1 = at least one does not.

param(
    [Parameter(Mandatory = $true)][string]$ManagerPath,
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$IpaPath
)

$ErrorActionPreference = 'Stop'

# .NET rather than Get-FileHash: on this machine that cmdlet disappears when the
# process inherits another PowerShell's PSModulePath (the same reason
# GameManager.ps1 hashes this way).
function Get-Sha256Hex {
    param([string]$Path)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '')
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

foreach ($path in @($ManagerPath, $ExePath, $IpaPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Write-Host ("  FAIL  missing file: {0}" -f $path)
        exit 1
    }
}

$managerText = [System.IO.File]::ReadAllText($ManagerPath)

$failed = $false
foreach ($pin in @(
    @{ Name = 'PinnedExeSha256'; Path = $ExePath; Label = 'touchHLE.exe' },
    @{ Name = 'PinnedIpaSha256'; Path = $IpaPath; Label = 'game IPA' }
)) {
    # Single-quoted prefix so the backslash-dollar reaches the regex as a literal
    # "$script:", which is how the constants are written in GameManager.ps1.
    $pattern = '\$script:' + $pin.Name + "\s*=\s*'([0-9A-Fa-f]{64})'"
    $match = [regex]::Match($managerText, $pattern)
    if (-not $match.Success) {
        Write-Host ("  FAIL  {0} not found in {1}" -f $pin.Name, $ManagerPath)
        $failed = $true
        continue
    }

    $expected = $match.Groups[1].Value.ToUpperInvariant()
    $actual = Get-Sha256Hex $pin.Path
    if ($expected -eq $actual) {
        Write-Host ("  OK    {0,-13} {1}" -f $pin.Label, $actual)
    } else {
        Write-Host ("  FAIL  {0,-13} pinned {1}" -f $pin.Label, $expected)
        Write-Host ("        {0,-13} actual {1}" -f '', $actual)
        $failed = $true
    }
}

if ($failed) {
    Write-Host ''
    Write-Host '  The pinned hashes in GameManager.ps1 do not match the current files.'
    Write-Host '  Update $script:PinnedExeSha256 / $script:PinnedIpaSha256 and retry.'
    exit 1
}
exit 0

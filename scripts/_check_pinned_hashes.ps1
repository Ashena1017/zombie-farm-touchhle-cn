# Verify the Windows manager's executable pin and the official release IPA.
param(
    [Parameter(Mandatory = $true)][string]$ManagerPath,
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$IpaPath,
    [string]$ManifestPath,
    [switch]$RequireManagerPins
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_file_hash.ps1')

$manager = [IO.File]::ReadAllText($ManagerPath)
$exeHash = [regex]::Match($manager, '\$script:PinnedExeSha256\s*=\s*''([a-fA-F0-9]{64})''').Groups[1].Value
$ipaHash = [regex]::Match($manager, '\$script:PinnedIpaSha256\s*=\s*''([a-fA-F0-9]{64})''').Groups[1].Value
$ipaName = [regex]::Match($manager, '\$script:BundledIpaName\s*=\s*''([^''\r\n]+)''').Groups[1].Value
if ($RequireManagerPins -and (-not $ipaHash -or -not $ipaName)) {
    throw 'The Windows manager must pin the official IPA filename and SHA-256.'
}
$ipa = Get-Item -LiteralPath $IpaPath
if ($ipaName -and $ipa.Name -cne $ipaName) {
    throw "The IPA filename differs from the manager pin: $ipaName"
}
if ($PSBoundParameters.ContainsKey('ManifestPath') -or -not $ipaHash) {
    if (-not $PSBoundParameters.ContainsKey('ManifestPath')) {
        $ManifestPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'release.json'
    }
    $releaseInfo = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath | ConvertFrom-Json
    if ($ipa.Name -cne $releaseInfo.ipa.name -or $ipa.Length -ne $releaseInfo.ipa.size) {
        throw "The IPA filename or size differs from $ManifestPath."
    }
    if ($ipaHash -and $ipaHash -ne $releaseInfo.ipa.sha256) {
        throw "The manager's IPA fingerprint differs from $ManifestPath."
    }
    # The v30 manager read its expected IPA identity from the manifest.
    $ipaHash = $releaseInfo.ipa.sha256
}

foreach ($pin in @(
    @{ Hash = $exeHash; Path = $ExePath; Label = 'touchHLE.exe' },
    @{ Hash = $ipaHash; Path = $IpaPath; Label = 'game IPA' }
)) {
    $actual = Get-Sha256Hex $pin.Path
    if ($actual -ne $pin.Hash) {
        throw "$($pin.Label) SHA-256 mismatch: expected '$($pin.Hash)', got '$actual'."
    }
    Write-Host ("  OK    {0,-13} {1}" -f $pin.Label, $actual)
}
exit 0

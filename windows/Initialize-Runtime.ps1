# Import runtime files from a portable Windows ZIP without copying the launcher or a save.
param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $project 'run\windows'
$emulator = Join-Path $runtime 'touchHLE'
$ipaDir = Join-Path $project 'zombie_farm_ipa'
$ipaName = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa'
$archive = (Resolve-Path -LiteralPath $ZipPath).Path
$temp = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd('\')
$stage = Join-Path $temp ('zfr-runtime-' + [Guid]::NewGuid().ToString('N'))

Add-Type -AssemblyName System.IO.Compression.FileSystem
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $stage)
    $roots = @(Get-ChildItem -LiteralPath $stage -Force)
    if ($roots.Count -ne 1 -or -not $roots[0].PSIsContainer) {
        throw 'Expected a Windows ZIP with a single top-level directory.'
    }
    $bundle = $roots[0].FullName
    $source = Join-Path $bundle 'touchHLE'
    $sourceIpa = Join-Path $bundle "zombie_farm_ipa\$ipaName"
    $files = @('touchHLE.exe', 'touchHLE_default_options.txt')
    $directories = @('touchHLE_dylibs', 'touchHLE_fonts')
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $file) -PathType Leaf)) { throw "Missing file: $file" }
    }
    foreach ($directory in $directories) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $directory) -PathType Container)) { throw "Missing directory: $directory" }
    }
    & (Join-Path $project 'scripts\_check_pinned_hashes.ps1') -ManagerPath (Join-Path $PSScriptRoot 'GameManager.ps1') -ExePath (Join-Path $source 'touchHLE.exe') -IpaPath $sourceIpa
    if ($LASTEXITCODE -ne 0) { throw 'The ZIP does not match the pinned Windows runtime.' }

    New-Item -ItemType Directory -Path $emulator, $ipaDir -Force | Out-Null
    $ipaLink = Join-Path $runtime 'zombie_farm_ipa'
    $link = Get-Item -LiteralPath $ipaLink -Force -ErrorAction SilentlyContinue
    if ($link -and $link.LinkType -ne 'Junction') {
        throw "Expected a junction from $ipaLink to $ipaDir."
    }
    if ($link -and @($link.Target)[0] -ne $ipaDir) {
        # A checkout moved to another directory retains the old absolute target.
        [IO.Directory]::Delete($ipaLink)
        $link = $null
    }
    if (-not $link) {
        New-Item -ItemType Junction -Path $ipaLink -Target $ipaDir | Out-Null
    }

    foreach ($name in $files + $directories) {
        $destination = Join-Path $emulator $name
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath (Join-Path $source $name) -Destination $destination -Recurse
        }
    }
    $destinationIpa = Join-Path $ipaDir $ipaName
    if (-not (Test-Path -LiteralPath $destinationIpa)) {
        Copy-Item -LiteralPath $sourceIpa -Destination $destinationIpa
    }
    $options = Join-Path $emulator 'touchHLE_options.txt'
    if (-not (Test-Path -LiteralPath $options)) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'touchHLE_options.txt') -Destination $options
    }
    New-Item -ItemType Directory -Path (Join-Path $emulator 'touchHLE_sandbox') -Force | Out-Null
    Write-Host "Windows runtime: $runtime"
}
finally {
    $resolved = (Resolve-Path -LiteralPath $stage).Path
    if ((Split-Path -Parent $resolved) -ne $temp -or (Split-Path -Leaf $resolved) -notmatch '^zfr-runtime-[a-f0-9]{32}$') {
        throw "Unexpected extraction directory: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

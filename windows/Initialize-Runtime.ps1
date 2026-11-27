# Import runtime files from a portable Windows ZIP without copying the launcher or a save.
param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
. (Join-Path $project 'scripts\_file_hash.ps1')
$runtime = Join-Path $project 'run\windows'
$emulator = Join-Path $runtime 'touchHLE'
$ipaDir = Join-Path $project 'zombie_farm_ipa'
$releaseInfo = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $project 'release.json') | ConvertFrom-Json
$ipaName = $releaseInfo.ipa.name
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
    $pinSource = Join-Path $PSScriptRoot 'GameManager.ps1'
    $zipPin = Join-Path $PSScriptRoot 'bootstrap-zip.sha256'
    if ((Test-Path -LiteralPath $zipPin -PathType Leaf) -and (Get-Sha256Hex $archive) -eq [IO.File]::ReadAllText($zipPin).Trim()) {
        # A fresh maintenance checkout can seed its dependencies from the published portable release.
        $pinSource = Join-Path $bundle 'GameManager.ps1'
    }
    & (Join-Path $project 'scripts\_check_pinned_hashes.ps1') -ManagerPath $pinSource -ManifestPath (Join-Path $project 'release.json') -ExePath (Join-Path $source 'touchHLE.exe') -IpaPath $sourceIpa
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

    function Install-RuntimeFile([string]$From, [string]$To) {
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $To))
        if (-not [IO.File]::Exists($To)) { [IO.File]::Copy($From, $To, $false) }
        if ((Get-Sha256Hex $From) -ne (Get-Sha256Hex $To)) {
            throw "Existing runtime file differs from the verified ZIP: $To"
        }
    }
    foreach ($name in $files) { Install-RuntimeFile (Join-Path $source $name) (Join-Path $emulator $name) }
    foreach ($directory in $directories) {
        $members = @(Get-ChildItem -File -Recurse -LiteralPath (Join-Path $source $directory))
        if (-not $members.Count) { throw "Runtime ZIP contains an empty $directory directory." }
        foreach ($member in $members) {
            $relative = $member.FullName.Substring($source.Length + 1)
            Install-RuntimeFile $member.FullName (Join-Path $emulator $relative)
        }
    }
    Install-RuntimeFile $sourceIpa (Join-Path $ipaDir $ipaName)
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

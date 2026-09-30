param(
    [string]$DestinationRoot = "Z:\",
    [string]$Configuration = "release"
)

$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
$ReleaseDir = Join-Path $RepoRoot "target\$Configuration"
$PackageName = "touchHLE-zombiefarm-windows-x64"
$DestinationDir = Join-Path $DestinationRoot $PackageName
$ZipPath = Join-Path $DestinationRoot "$PackageName.zip"

function Copy-RequiredItem {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $Source = Join-Path $RepoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing required file or directory: $Source"
    }

    $Target = Join-Path $DestinationDir $RelativePath
    $TargetParent = Split-Path -Parent $Target
    if (-not (Test-Path -LiteralPath $TargetParent)) {
        New-Item -ItemType Directory -Path $TargetParent | Out-Null
    }

    Copy-Item -LiteralPath $Source -Destination $Target -Recurse -Force
}

function Copy-RuntimeDll {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $Candidates = @(
        (Join-Path $ReleaseDir $Name),
        (Join-Path $env:WINDIR "System32\$Name")
    )

    $Source = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($Source) {
        Copy-Item -LiteralPath $Source -Destination (Join-Path $DestinationDir $Name) -Force
    } else {
        Write-Warning "Could not find optional runtime DLL: $Name"
    }
}

if (-not (Test-Path -LiteralPath $DestinationRoot)) {
    throw "Destination root does not exist: $DestinationRoot"
}

$ExePath = Join-Path $ReleaseDir "touchHLE.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build output not found: $ExePath. Run .\build_windows.bat first."
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

if (Test-Path -LiteralPath $DestinationDir) {
    Get-ChildItem -LiteralPath $DestinationDir -Force | Remove-Item -Recurse -Force
} else {
    New-Item -ItemType Directory -Path $DestinationDir | Out-Null
}

Copy-Item -LiteralPath $ExePath -Destination (Join-Path $DestinationDir "touchHLE.exe") -Force

Copy-RequiredItem "touchHLE_dylibs"
Copy-RequiredItem "touchHLE_fonts"
Copy-RequiredItem "zombie_farm"
Copy-RequiredItem "LICENSE"

$OptionsFiles = @(
    "touchHLE_default_options.txt",
    "touchHLE_options.txt"
)
foreach ($OptionsFile in $OptionsFiles) {
    $Source = Join-Path $RepoRoot $OptionsFile
    $Target = Join-Path $DestinationDir $OptionsFile
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing required options file: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Target -Force
    if (-not (Test-Path -LiteralPath $Target)) {
        throw "Failed to copy options file: $Target"
    }
}

Copy-RuntimeDll "MSVCP140.dll"
Copy-RuntimeDll "VCRUNTIME140.dll"
Copy-RuntimeDll "VCRUNTIME140_1.dll"

$LauncherPath = Join-Path $DestinationDir "run_touchHLE_zombiefarm_windows_x64.bat"
@"
@echo off
cd /d "%~dp0"
touchHLE.exe %*
"@ | Set-Content -LiteralPath $LauncherPath -Encoding ASCII

$ZombieFarmLauncherPath = Join-Path $DestinationDir "run_ZFR06_ipad_landscape_left.bat"
@"
@echo off
cd /d "%~dp0"
touchHLE.exe ".\zombie_farm\ZFR06.ipa" --device-family="ipad" --landscape-left
"@ | Set-Content -LiteralPath $ZombieFarmLauncherPath -Encoding ASCII

$ZipItems = Get-ChildItem -LiteralPath $DestinationDir -Force |
    Where-Object { $_.Name -ne "zombie_farm" } |
    ForEach-Object { $_.FullName }
Compress-Archive -Path $ZipItems -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "Package folder: $DestinationDir"
Write-Host "Zip archive:    $ZipPath"

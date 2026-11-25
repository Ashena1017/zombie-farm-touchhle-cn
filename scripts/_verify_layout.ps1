$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$required = @(
    'Play-Windows.bat',
    'windows\GameManager.ps1',
    'windows\compat\WinForms.ps1',
    'windows\ManagerWorker.ps1',
    'windows\launcher\Cargo.toml',
    'windows\launcher\ui\index.html',
    'windows\RepositoryPaths.ps1',
    'windows\touchHLE_options.txt',
    'touchHLE\touchHLE-fork\Cargo.toml',
    'run\windows\touchHLE\touchHLE.exe',
    'run\windows\touchHLE\touchHLE_options.txt',
    'run\windows\touchHLE\touchHLE_dylibs',
    'run\windows\touchHLE\touchHLE_fonts',
    'run\windows\touchHLE\touchHLE_sandbox'
)
foreach ($entry in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $project $entry))) {
        throw "Missing project path: $entry"
    }
}
foreach ($legacy in @('GameManager.ps1', 'touchHLE\touchHLE.exe', 'touchHLE\touchHLE_sandbox', 'Release', 'touchHLE-zombiefarm-android-arm64')) {
    if (Test-Path -LiteralPath (Join-Path $project $legacy)) {
        throw "Old project path still present: $legacy"
    }
}
$ipaLink = Get-Item -LiteralPath (Join-Path $project 'run\windows\zombie_farm_ipa') -Force
if ($ipaLink.LinkType -ne 'Junction' -or @($ipaLink.Target)[0] -ne (Join-Path $project 'zombie_farm_ipa')) {
    throw 'The emulator IPA directory must point to the shared IPA directory.'
}
Write-Host 'RESULT: PASS - project layout and shared IPA'

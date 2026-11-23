# Validate the portable ZIP's layout and checksums without opening the game.
param(
    [string]$ZipPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\windows\zombie-farm-windows-x64.zip')
)
& (Join-Path $PSScriptRoot '_verify_release.ps1') -ZipPath $ZipPath -LayoutOnly
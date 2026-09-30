# Install a self-contained Rust toolchain for building touchHLE from
# touchHLE-fork, without touching the user's broken ~/.rustup install.
#
# Everything lands under _build_tools/ so it can be deleted in one go.
$ErrorActionPreference = 'Stop'

$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

$tools = Join-Path $hleRoot '_build_tools'
$rustupHome = Join-Path $tools 'rustup'
$cargoHome = Join-Path $tools 'cargo'
$dl = Join-Path $tools 'downloads'

New-Item -ItemType Directory -Force -Path $rustupHome, $cargoHome, $dl | Out-Null

$env:RUSTUP_HOME = $rustupHome
$env:CARGO_HOME = $cargoHome

$initExe = Join-Path $dl 'rustup-init.exe'
if (-not (Test-Path $initExe)) {
    Write-Host "Downloading rustup-init.exe ..."
    $url = 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe'
    Invoke-WebRequest -Uri $url -OutFile $initExe -UseBasicParsing -TimeoutSec 300
}
Write-Host "rustup-init.exe: $((Get-Item $initExe).Length) bytes"

Write-Host "Installing stable-x86_64-pc-windows-msvc (minimal profile) ..."
& $initExe -y --no-modify-path --profile minimal --default-toolchain stable-x86_64-pc-windows-msvc
Write-Host "rustup-init exit=$LASTEXITCODE"

$rustc = Join-Path $rustupHome 'toolchains\stable-x86_64-pc-windows-msvc\bin\rustc.exe'
$cargo = Join-Path $rustupHome 'toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe'
Write-Host "--- verify ---"
& $rustc --version
Write-Host "rustc exit=$LASTEXITCODE"
& $cargo --version
Write-Host "cargo exit=$LASTEXITCODE"
Write-Host "DONE"

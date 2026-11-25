# Build the portable Tauri manager, including its local UI.
param([string]$Destination = (Join-Path (Split-Path -Parent $PSScriptRoot) '游戏管理.exe'))
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$localTools = Join-Path $root 'touchHLE\_build_tools'
if (-not (Get-Command cargo.exe -ErrorAction SilentlyContinue)) {
    $rustup = if ($env:RUSTUP_HOME) { $env:RUSTUP_HOME } else { Join-Path $env:USERPROFILE '.rustup' }
    $cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE '.cargo' }
    $bins = @((Join-Path $cargoHome 'bin'), (Join-Path $rustup 'toolchains\stable-x86_64-pc-windows-msvc\bin'))
    $bin = $bins | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'cargo.exe') } | Select-Object -First 1
    if (-not $bin -and (Test-Path -LiteralPath "$localTools\cargo\bin\cargo.exe")) {
        $env:CARGO_HOME = Join-Path $localTools 'cargo'
        $env:RUSTUP_HOME = Join-Path $localTools 'rustup'
        $bin = Join-Path $env:CARGO_HOME 'bin'
    }
    if ($bin) { $env:PATH = "$bin;$env:PATH" }
}
$cargo = (Get-Command cargo.exe -ErrorAction Stop).Source
$Destination = [IO.Path]::GetFullPath($Destination)
Push-Location -LiteralPath $PSScriptRoot
try {
    $exe = & $cargo build --locked --release --bin zf-manager --message-format=json-render-diagnostics | ForEach-Object {
        $message = $_ | ConvertFrom-Json
        if ($message.reason -eq 'compiler-artifact' -and $message.target.name -eq 'zf-manager' -and $message.executable) {
            $message.executable
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Tauri manager build failed (exit $LASTEXITCODE)." }
    if (-not $exe) { throw 'Cargo did not report the built manager executable.' }
    $destinationDir = Split-Path -Parent $Destination
    $tempExe = Join-Path $destinationDir ('.zf-manager-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::Copy($exe, $tempExe)
        if ([IO.File]::Exists($Destination)) {
            if ((Get-FileHash -LiteralPath $tempExe).Hash -ne (Get-FileHash -LiteralPath $Destination).Hash) {
                [IO.File]::Replace($tempExe, $Destination, [NullString]::Value)
            }
        } else {
            [IO.File]::Move($tempExe, $Destination)
        }
    } finally {
        if ([IO.File]::Exists($tempExe)) { [IO.File]::Delete($tempExe) }
    }
    Write-Host "Windows manager: $Destination"
} finally {
    Pop-Location
}

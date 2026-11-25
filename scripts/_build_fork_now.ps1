# Rebuild touchHLE and install the emulator the repository launcher uses.
param([string]$VsDevCmd)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$paths = & (Join-Path $root 'windows\RepositoryPaths.ps1')
$fork = Join-Path $root 'touchHLE\touchHLE-fork'
$tools = Join-Path $root 'touchHLE\_build_tools'
$log = Join-Path $root '_analysis\_build_fork_now.log'

if (-not $env:CARGO_HOME -and (Test-Path -LiteralPath "$tools\cargo\bin\cargo.exe")) {
    $env:CARGO_HOME = Join-Path $tools 'cargo'
}
if (-not $env:RUSTUP_HOME -and (Test-Path -LiteralPath "$tools\rustup\settings.toml")) {
    $env:RUSTUP_HOME = Join-Path $tools 'rustup'
}
if ($env:CARGO_HOME -and (Test-Path -LiteralPath "$env:CARGO_HOME\bin\cargo.exe")) {
    $env:Path = "$env:CARGO_HOME\bin;$env:Path"
}
if (-not (Get-Command cargo.exe -ErrorAction SilentlyContinue)) {
    throw 'Install Rust with the x86_64-pc-windows-msvc toolchain or set CARGO_HOME.'
}
if (-not $env:CARGO_TARGET_DIR) {
    $env:CARGO_TARGET_DIR = if (Test-Path -LiteralPath $tools) {
        Join-Path $tools 'target-fork'
    } else { Join-Path $fork 'target' }
}
if (-not [IO.Path]::IsPathRooted($env:CARGO_TARGET_DIR)) {
    $env:CARGO_TARGET_DIR = Join-Path $fork $env:CARGO_TARGET_DIR
}
$env:CMAKE_POLICY_VERSION_MINIMUM = '3.5'

$activate = $VsDevCmd -or $env:VSCMD_ARG_TGT_ARCH -ne 'x64' -or -not (Get-Command cl.exe -ErrorAction SilentlyContinue)
if ($activate -and -not $VsDevCmd) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($vsRoot) { $VsDevCmd = Join-Path $vsRoot 'Common7\Tools\VsDevCmd.bat' }
    }
}
if ($activate -and (-not $VsDevCmd -or -not (Test-Path -LiteralPath $VsDevCmd -PathType Leaf))) {
    throw 'Open an x64 Visual Studio developer shell or provide -VsDevCmd with the path to VsDevCmd.bat.'
}

$command = 'cargo.exe build --locked --release --bin touchHLE'
if ($activate) {
    $env:ZF_DEV_CMD = (Resolve-Path -LiteralPath $VsDevCmd).Path
    $command = 'call "%ZF_DEV_CMD%" -no_logo -arch=x64 -host_arch=x64 && ' + $command
}
Push-Location -LiteralPath $fork
try {
    $env:ZF_BUILD_LOG = $log
    Write-Host "Building Windows x64. Compiler log: $log"
    & cmd.exe /d /c "($command) > `"%ZF_BUILD_LOG%`" 2>&1"
    $status = $LASTEXITCODE
    Get-Content -LiteralPath $log -Tail 25
    if ($status -ne 0) { throw "Windows build failed with exit code $status. See $log" }
    $exe = Join-Path $env:CARGO_TARGET_DIR 'release\touchHLE.exe'
    New-Item -ItemType Directory -Path $paths.Emulator -Force | Out-Null
    Copy-Item -LiteralPath $exe -Destination $paths.Emulator -Force
    Write-Host "Installed $exe to $($paths.Emulator)"
} finally {
    Pop-Location
}

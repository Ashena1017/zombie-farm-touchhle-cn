# Rebuild touchHLE from the fork source (incremental) and refresh the
# binaries used by the dev tree. Same environment as _build_fork.ps1.
$ErrorActionPreference = 'Continue'

$root   = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

$fork   = Join-Path $hleRoot 'touchHLE-fork'
$tools  = Join-Path $hleRoot '_build_tools'
$log    = Join-Path $root '_analysis\_build_fork_now.log'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}
Set-Content -LiteralPath $log -Value "build started $(Get-Date -Format o)" -Encoding utf8

$env:RUSTUP_HOME = Join-Path $tools 'rustup'
$env:CARGO_HOME  = Join-Path $tools 'cargo'
$env:CARGO_TARGET_DIR = Join-Path $tools 'target-fork'
$env:Path = "$tools\cargo\bin;$env:Path"

$cmakeBin = & python -c "import cmake,os;print(os.path.join(cmake.CMAKE_BIN_DIR,'cmake.exe'))" 2>$null
if ($cmakeBin -and (Test-Path $cmakeBin)) {
    $env:CMAKE = $cmakeBin
    $env:Path = "$(Split-Path $cmakeBin);$env:Path"
}
$env:CMAKE_POLICY_VERSION_MINIMUM = '3.5'

$vsDevCmd = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
$cargo = Join-Path $tools 'rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe'

Push-Location $fork
try {
    $out = Join-Path $env:TEMP 'thle_fork_build_now.out'
    Log 'cargo build --release --bin touchHLE'
    $inner = "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && set `"CARGO_TARGET_DIR=$env:CARGO_TARGET_DIR`" && `"$cargo`" build --release --bin touchHLE"
    & cmd.exe /c $inner *> $out
    $code = $LASTEXITCODE
    Log "cargo exit=$code"
    if (Test-Path $out) { Get-Content -LiteralPath $out -Tail 60 | ForEach-Object { Log "  | $_" } }

    $exe = Join-Path $env:CARGO_TARGET_DIR 'release\touchHLE.exe'
    if ($code -ne 0) {
        Log 'BUILD FAILED - binary NOT copied'
        exit 1
    }
    if (Test-Path $exe) {
        Log "BUILT: $exe ($((Get-Item $exe).Length) bytes, $((Get-Item $exe).LastWriteTime))"
        $dest = Join-Path $hleRoot 'touchHLE_fork.exe'
        Copy-Item -LiteralPath $exe -Destination $dest -Force
        Log "copied to $dest"
    } else {
        Log 'NO BINARY'
        exit 1
    }
} finally { Pop-Location }
Log 'build DONE'

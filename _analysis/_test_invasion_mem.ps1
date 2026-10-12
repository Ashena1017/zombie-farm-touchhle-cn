param([string]$Filter = 'allocation_origin_tests', [switch]$All)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$buildTools = Join-Path $workspace 'touchHLE\_build_tools'
$forkRoot = Join-Path $workspace 'touchHLE\touchHLE-fork'
$outputDir = Join-Path $PSScriptRoot 'dumps\player-invasion-20261012'
if ($All) { $Filter = '' }
$testLabel = if ($Filter.Length -eq 0) { 'all' } else { $Filter -replace '[^A-Za-z0-9_-]', '_' }
$logPath = Join-Path $outputDir ('production-' + $testLabel + '-tests.txt')
if ($Filter -notmatch '^[A-Za-z0-9_:]*$') { throw 'Invalid test filter.' }
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$env:RUSTUP_HOME = Join-Path $buildTools 'rustup'
$env:CARGO_HOME = Join-Path $buildTools 'cargo'
$env:CARGO_TARGET_DIR = Join-Path $buildTools 'target-fork'
$env:Path = "$buildTools\cargo\bin;$env:Path"
$cmakeBin = & python -c "import cmake,os;print(os.path.join(cmake.CMAKE_BIN_DIR,'cmake.exe'))"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $cmakeBin)) { throw 'Configured CMake is unavailable.' }
$env:CMAKE = $cmakeBin
$env:Path = "$(Split-Path -Parent $cmakeBin);$env:Path"
$env:CMAKE_POLICY_VERSION_MINIMUM = '3.5'
$vsDevCmd = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
$cargoExe = Join-Path $buildTools 'rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe'
$inner = "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && `"$cargoExe`" test --release --lib $Filter -- --test-threads=1"
Write-Host "Production lib tests: $Filter; output: $logPath"
Push-Location $forkRoot
try {
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & cmd.exe /c $inner *> $logPath
    $code = $LASTEXITCODE
    $ErrorActionPreference = $savedPreference
    Get-Content -LiteralPath $logPath -Tail 80 -Encoding UTF8
    if ($code -ne 0) { throw "Production lib tests failed (exit $code)." }
} finally { Pop-Location }

# Build the ACTUAL fork source (upstream commit fa3d095, the one the user's
# touchHLE.exe reports) instead of trunk, after applying the zero-timeout
# run-loop fix to it.
#
# Why the fork and not trunk: fa3d095 carries the Zombie Farm adaptation (185
# references, plus 21 fork-only source files). Trunk does not, and a trunk build
# aborts on the app in NSMutableDictionary +allocWithZone:.
#
# The fork's vendor/ dependencies are REAL directories owned by the fork. They
# used to be NTFS junctions into touchHLE-trunk\vendor, which meant deleting the
# trunk silently broke every build; _analysis\_restore_vendor.ps1 repopulated
# them in place and this script no longer touches the trunk at all. If a
# dependency ever goes missing, run that script rather than re-linking.
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
$log    = Join-Path $root '_analysis\_build_fork.log'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}
Set-Content -LiteralPath $log -Value "fork build started $(Get-Date -Format o)" -Encoding utf8

function Run([string]$exe, [string[]]$argv, [string]$tag) {
    $tmp = Join-Path $env:TEMP "forkb_$tag.out"
    & $exe @argv *> $tmp
    $code = $LASTEXITCODE
    if (Test-Path $tmp) {
        Get-Content -LiteralPath $tmp -Tail 4 -ErrorAction SilentlyContinue |
            ForEach-Object { Log "    | $_" }
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
    if ($code -ne 0) { Log "  ! exit=$code" }
    return $code
}

$forkVendor = Join-Path $fork 'vendor'
New-Item -ItemType Directory -Force -Path $forkVendor | Out-Null

# --- verify every vendor dependency is present and real --------------------
# A junction to a deleted target is invisible to Test-Path, so check the link
# type as well as the contents.
$required = @('SDL', 'openal-soft', 'stb', 'boost', 'dynarmic', 'PVRTDecompress')
$missing = @()
foreach ($d in $required) {
    $p = Join-Path $forkVendor $d
    $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
    $files = if ($item) {
        (Get-ChildItem -LiteralPath $p -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object).Count
    } else { 0 }
    $link = if ($item -and $item.LinkType) { $item.LinkType } else { 'real' }
    if ($files -le 0) {
        Log "vendor $d : MISSING or EMPTY (link=$link)"
        $missing += $d
    } else {
        Log "vendor $d : ok ($files files, $link)"
    }
}
if ($missing.Count -gt 0) {
    Log "STOP: missing vendor deps: $($missing -join ', ')"
    Log "      run _analysis\_restore_vendor.ps1 to fetch them"
    exit 1
}

# --- build ------------------------------------------------------------------
$env:RUSTUP_HOME = Join-Path $tools 'rustup'
$env:CARGO_HOME  = Join-Path $tools 'cargo'
$env:CARGO_TARGET_DIR = Join-Path $tools 'target-fork'
$env:Path = "$tools\cargo\bin;$env:Path"

$cmakeBin = & python -c "import cmake,os;print(os.path.join(cmake.CMAKE_BIN_DIR,'cmake.exe'))" 2>$null
if ($cmakeBin -and (Test-Path $cmakeBin)) {
    $env:CMAKE = $cmakeBin
    $env:Path = "$(Split-Path $cmakeBin);$env:Path"
    Log "cmake: $cmakeBin"
}
$env:CMAKE_POLICY_VERSION_MINIMUM = '3.5'

$vsDevCmd = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
$cargo = Join-Path $tools 'rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe'

Push-Location $fork
try {
    $out = Join-Path $env:TEMP 'thle_fork_build.out'
    Log 'cargo build --release --bin touchHLE  (fork source)'
    $inner = "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && set `"CARGO_TARGET_DIR=$env:CARGO_TARGET_DIR`" && `"$cargo`" build --release --bin touchHLE"
    & cmd.exe /c $inner *> $out
    $code = $LASTEXITCODE
    Log "cargo exit=$code"
    if (Test-Path $out) { Get-Content -LiteralPath $out -Tail 45 | ForEach-Object { Log "  | $_" } }

    $exe = Join-Path $env:CARGO_TARGET_DIR 'release\touchHLE.exe'
    if (Test-Path $exe) {
        Log "BUILT: $exe  ($((Get-Item $exe).Length) bytes)"
        $dest = Join-Path $hleRoot 'touchHLE_fork.exe'
        Copy-Item -LiteralPath $exe -Destination $dest -Force
        Log "copied to $dest  ($((Get-Item $dest).Length) bytes)"
    } else {
        Log 'NO BINARY'
    }
} finally { Pop-Location }
Log 'fork build DONE'

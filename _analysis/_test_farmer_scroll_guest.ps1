# Run the original IPA's table-cell getters against the production predicate
# implementation. Uses the read-only guest FS; never starts the game's loop.
param([switch]$All, [string]$IpaPath)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$buildTools = Join-Path $root 'touchHLE\_build_tools'
$env:RUSTUP_HOME = Join-Path $buildTools 'rustup'
$env:CARGO_HOME = Join-Path $buildTools 'cargo'
$env:CARGO_TARGET_DIR = Join-Path $buildTools 'target-fork'
$env:Path = "$env:CARGO_HOME\bin;$env:Path"
$env:ZFR_GUEST_TEST_IPA = if ($IpaPath) { $IpaPath } else {
    Join-Path $root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa'
}
$vsDevCmd = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
$cargoExe = Join-Path $buildTools 'rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe'
$manifest = Join-Path $root 'touchHLE\touchHLE-fork\Cargo.toml'
$cmakeBin = & python -c "import cmake,os;print(os.path.join(cmake.CMAKE_BIN_DIR,'cmake.exe'))"
if ($LASTEXITCODE -ne 0) { throw 'Configured CMake is unavailable.' }
$env:CMAKE = $cmakeBin
$env:Path = "$(Split-Path -Parent $cmakeBin);$env:Path"
$env:CMAKE_POLICY_VERSION_MINIMUM = '3.5'
$out = Join-Path $PSScriptRoot 'dumps\farmer-scroll-20261117'
New-Item -ItemType Directory -Path $out -Force | Out-Null
$testArgs = if ($All) { '-- --test-threads=1' } else {
    'guest_table_predicates_keep_visible_cells -- --ignored --test-threads=1 --nocapture'
}
$log = Join-Path $out $(if ($All) { 'library-tests-final.txt' } else { 'guest-predicates-final.txt' })
$inner = "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && `"$cargoExe`" test --release --lib --manifest-path `"$manifest`" $testArgs"
$ErrorActionPreference = 'Continue'
& cmd.exe /c $inner *> $log
$code = $LASTEXITCODE
Get-Content -LiteralPath $log -Encoding UTF8 -Tail 15
if ($code -ne 0) { throw "Farmer/scroll production tests failed ($code)." }

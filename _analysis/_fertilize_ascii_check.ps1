# Does the game's plist loader accept the legacy `"key" = "value";` .strings format?
#
# Why this matters: the legacy text format compresses to 160 bytes, which WOULD
# fit the 189-byte ZIP slot with the faithful text ' %@施肥了' intact.  If the
# loader accepts it, v19's shortening was avoidable.
#
# Evidence chain (all static, already confirmed):
#   * the game loads the table via -[NSBundle localizedStringForKey:value:table:]
#     -> [NSDictionary dictionaryWithContentsOfURL:]
#     (touchHLE-fork/src/frameworks/foundation/ns_bundle.rs:254)
#   * -> deserialize_plist_from_file -> plist::Value::from_reader
#     (ns_property_list_serialization.rs:133)
#   * the plist crate's Reader::init auto-detects: binary magic -> binary,
#     else try XML, else fall back to the ASCII/OpenStep reader
#     (plist-1.8.0/src/stream/mod.rs)
#
# This script compiles a 5-line Rust program against the SAME crate version the
# emulator uses, and prints what it parses.  ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)
$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}


$ErrorActionPreference = 'Continue'
$tools = Join-Path $hleRoot '_build_tools'

$env:RUSTUP_HOME = Join-Path $tools 'rustup'
$env:CARGO_HOME = Join-Path $tools 'cargo'
$env:CARGO_TARGET_DIR = Join-Path $tools 'target-plisttest'
$env:Path = "$tools\cargo\bin;$env:Path"
$env:RUSTUP_TOOLCHAIN = 'stable-x86_64-pc-windows-msvc'

$vsDevCmd = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
$cargo = Join-Path $tools 'rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe'

if (-not (Test-Path $cargo)) { Write-Host "FAIL: no cargo at $cargo"; exit 1 }
if (-not (Test-Path $vsDevCmd)) { Write-Host "FAIL: no VsDevCmd"; exit 1 }

$dir = Join-Path $env:TEMP ('plisttest_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path (Join-Path $dir 'src') | Out-Null

$toml = @'
[package]
name = "plisttest"
version = "0.0.0"
edition = "2021"

[dependencies]
plist = "1.8.0"
'@
[System.IO.File]::WriteAllText((Join-Path $dir 'Cargo.toml'), $toml,
    (New-Object System.Text.UTF8Encoding($false)))

# The legacy .strings bytes: "Fertilized by %@!" = " %@施肥了";
$legacy = '"Fertilized by %@!" = " %@' + [char]0x65BD + [char]0x80A5 + [char]0x4E86 + '";' + "`n" +
          '"Zombee" = "' + [char]0x871C + [char]0x8702 + [char]0x50F5 + [char]0x5C38 + '";' + "`n"
[System.IO.File]::WriteAllText((Join-Path $dir 'legacy.strings'), $legacy,
    (New-Object System.Text.UTF8Encoding($false)))

$rs = @'
fn main() {
    let path = std::env::args().nth(1).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    println!("input {} bytes, first 16: {:02x?}", bytes.len(), &bytes[..16.min(bytes.len())]);
    let mut cur = std::io::Cursor::new(bytes);
    match plist::Value::from_reader(&mut cur) {
        Ok(v) => {
            println!("PARSED OK");
            if let Some(d) = v.as_dictionary() {
                let mut keys: Vec<_> = d.iter().collect();
                keys.sort_by_key(|(k, _)| k.clone());
                for (k, val) in keys {
                    println!("  {} => {:?}", k, val.as_string());
                }
            } else {
                println!("  (root is not a dictionary)");
            }
        }
        Err(e) => println!("PARSE FAILED: {}", e),
    }
}
'@
[System.IO.File]::WriteAllText((Join-Path $dir 'src\main.rs'), $rs,
    (New-Object System.Text.UTF8Encoding($false)))

Write-Host "== building the probe =="
$out = Join-Path $env:TEMP 'plisttest_build.out'
$inner = "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && set `"CARGO_TARGET_DIR=$env:CARGO_TARGET_DIR`" && `"$cargo`" build --offline --quiet"
Push-Location $dir
& cmd.exe /c $inner *> $out
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) {
    Write-Host "build failed (exit $code)"
    if (Test-Path $out) { Get-Content $out -Tail 15 | ForEach-Object { Write-Host "  | $_" } }
    Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

$exe = Join-Path $env:CARGO_TARGET_DIR 'debug\plisttest.exe'
if (-not (Test-Path $exe)) { Write-Host "FAIL: no $exe"; exit 1 }

Write-Host ''
Write-Host "== parsing the legacy .strings text format =="
$legacyOut = & $exe (Join-Path $dir 'legacy.strings') 2>&1
$legacyOut | ForEach-Object { Write-Host "  $_" }
# NOTE: the probe exits 0 whether or not the parse succeeded, so the verdict must
# come from its OUTPUT.  An earlier version of this script used $LASTEXITCODE and
# reported PASS on a failed parse.
$legacyOk = ($legacyOut -join "`n") -match 'PARSED OK'

Write-Host ''
Write-Host "== variant: OpenStep dictionary with enclosing braces =="
$braced = '{ "Fertilized by %@!" = " %@' + [char]0x65BD + [char]0x80A5 + [char]0x4E86 + '";' + "`n" +
          '  "Zombee" = "' + [char]0x871C + [char]0x8702 + [char]0x50F5 + [char]0x5C38 + '"; }' + "`n"
$bracedPath = Join-Path $dir 'braced.strings'
[System.IO.File]::WriteAllText($bracedPath, $braced, (New-Object System.Text.UTF8Encoding($false)))
$bracedOut = & $exe $bracedPath 2>&1
$bracedOut | ForEach-Object { Write-Host "  $_" }
$bracedOk = ($bracedOut -join "`n") -match 'PARSED OK'

Write-Host ''
Write-Host "== variant: single entry, no braces =="
$one = '"Fertilized by %@!" = " %@' + [char]0x65BD + [char]0x80A5 + [char]0x4E86 + '";' + "`n"
$onePath = Join-Path $dir 'one.strings'
[System.IO.File]::WriteAllText($onePath, $one, (New-Object System.Text.UTF8Encoding($false)))
$oneOut = & $exe $onePath 2>&1
$oneOut | ForEach-Object { Write-Host "  $_" }
$oneOk = ($oneOut -join "`n") -match 'PARSED OK'

Write-Host ''
Write-Host "== control: parsing a binary plist (what the game ships today) =="
$bp = Join-Path $dir 'control.bplist'
Copy-Item -LiteralPath (Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v28fix.ipa') -Destination (Join-Path $dir 'x.ipa')
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Join-Path $dir 'x.ipa'))
$entry = $zip.Entries | Where-Object { $_.FullName -eq 'Payload/ZFR.app/Arial-BoldMT.strings' }
$fs = $entry.Open()
$ms = New-Object System.IO.MemoryStream
$fs.CopyTo($ms); $fs.Close(); $zip.Dispose()
[System.IO.File]::WriteAllBytes($bp, $ms.ToArray())
& $exe $bp

Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:TEMP 'plisttest_build.out') -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host ("legacy (no braces) : " + $(if ($legacyOk) { 'PARSED' } else { 'rejected' }))
Write-Host ("legacy (braced)    : " + $(if ($bracedOk) { 'PARSED' } else { 'rejected' }))
Write-Host ("legacy (single)    : " + $(if ($oneOk) { 'PARSED' } else { 'rejected' }))
Write-Host ''
if ($legacyOk -or $bracedOk -or $oneOk) {
    Write-Host 'RESULT: the loader CAN read the legacy text format'
    exit 0
}
Write-Host 'RESULT: the loader rejects every legacy text variant tested'
exit 1

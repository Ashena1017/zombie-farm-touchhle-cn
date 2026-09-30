# Parse the REAL v29fix member bytes with the game's actual plist loader.
#
# v29fix re-serialises Arial-BoldMT.strings from a binary plist to an OpenStep
# text plist.  Static reasoning and a synthetic probe both say the loader accepts
# it, but the decisive check is the SHIPPED BYTES: extract them from the IPA and
# feed them to plist::Value::from_reader (crate 1.8.0, same as the emulator).
#
# This also reproduces the exact call the game makes: it reads the table via
# [NSDictionary dictionaryWithContentsOfURL:], i.e. deserialize_plist_from_file,
# which requires the root to be a DICTIONARY (not an array).
#
# ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Ipa = 'Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
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

$ipaPath = if ([System.IO.Path]::IsPathRooted($Ipa)) { $Ipa } else { Join-Path $Root ('zombie_farm_ipa\' + $Ipa) }
if (-not (Test-Path $ipaPath)) { Write-Host "FAIL: no IPA at $ipaPath"; exit 1 }

$dir = Join-Path $env:TEMP ('v29probe_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path (Join-Path $dir 'src') | Out-Null

# ---- extract the two members ------------------------------------------------
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($ipaPath)
$targets = @('Payload/ZFR.app/Arial-BoldMT.strings',
             'Payload/ZFR.app/zh-Hans.lproj/Arial-BoldMT.strings')
$extracted = @{}
foreach ($t in $targets) {
    $e = $zip.Entries | Where-Object { $_.FullName -eq $t }
    if (-not $e) { Write-Host "FAIL: member not found: $t"; $zip.Dispose(); exit 1 }
    $ms = New-Object System.IO.MemoryStream
    $s = $e.Open(); $s.CopyTo($ms); $s.Close()
    $bytes = $ms.ToArray()
    $safe = ($t -replace '[\\/]', '_')
    $p = Join-Path $dir $safe
    [System.IO.File]::WriteAllBytes($p, $bytes)
    $extracted[$t] = $p
    Write-Host ("extracted {0}  ({1} bytes)" -f $t, $bytes.Length)
    $ms.Dispose()
}
$zip.Dispose()

# ---- probe ------------------------------------------------------------------
$toml = @'
[package]
name = "v29probe"
version = "0.0.0"
edition = "2021"

[dependencies]
plist = "1.8.0"
'@
[System.IO.File]::WriteAllText((Join-Path $dir 'Cargo.toml'), $toml,
    (New-Object System.Text.UTF8Encoding($false)))

$rs = @'
use std::collections::BTreeMap;

fn main() {
    let mut bad = 0;
    for path in std::env::args().skip(1) {
        let bytes = std::fs::read(&path).unwrap();
        let head = String::from_utf8_lossy(&bytes[..bytes.len().min(24)]).to_string();
        println!("--- {}", path);
        println!("    {} bytes, starts: {:?}", bytes.len(), head);
        let mut cur = std::io::Cursor::new(bytes);
        match plist::Value::from_reader(&mut cur) {
            Ok(v) => {
                let Some(d) = v.as_dictionary() else {
                    println!("    REJECTED: root is not a dictionary");
                    bad += 1;
                    continue;
                };
                // The game asks for one key and asserts the dict is non-nil.
                println!("    PARSED OK, {} entries", d.len());
                let mut sorted: BTreeMap<String, String> = BTreeMap::new();
                for (k, val) in d {
                    sorted.insert(k.clone(), val.as_string().unwrap_or("<not a string>").to_string());
                }
                for (k, val) in &sorted {
                    println!("      {} => {:?}", k, val);
                }
                // Compare by code points, not by a literal: writing the expected
                // Chinese inline in a Rust source file that PowerShell wrote as
                // UTF-8-without-BOM made rustc mis-decode it, so the earlier
                // version reported a mismatch for a byte-identical string.
                let expected: Vec<u32> = vec![0x20, 0x25, 0x40, 0x65BD, 0x80A5,
                                              0x5566, 0xFF01];
                match sorted.get("Fertilized by %@!") {
                    Some(v) => {
                        let got: Vec<u32> = v.chars().map(|c| c as u32).collect();
                        if got == expected {
                            println!("    FERTILIZE VALUE OK: {:?}", v);
                        } else {
                            println!("    FERTILIZE VALUE WRONG: {:?} -> {:04X?}", v, got);
                            bad += 1;
                        }
                    }
                    None => { println!("    FERTILIZE KEY MISSING"); bad += 1; }
                }
            }
            Err(e) => { println!("    PARSE FAILED: {}", e); bad += 1; }
        }
    }
    std::process::exit(if bad == 0 { 0 } else { 1 });
}
'@
[System.IO.File]::WriteAllText((Join-Path $dir 'src\main.rs'), $rs,
    (New-Object System.Text.UTF8Encoding($false)))

Write-Host ''
Write-Host '== building the probe =='
$out = Join-Path $env:TEMP 'v29probe_build.out'
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

$exe = Join-Path $env:CARGO_TARGET_DIR 'debug\v29probe.exe'
if (-not (Test-Path $exe)) { Write-Host "FAIL: no $exe"; exit 1 }

Write-Host ''
Write-Host '== feeding the SHIPPED member bytes to plist 1.8.0 =='
& $exe $extracted[$targets[0]] $extracted[$targets[1]]
$probeCode = $LASTEXITCODE

Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:TEMP 'v29probe_build.out') -Force -ErrorAction SilentlyContinue

Write-Host ''
if ($probeCode -eq 0) {
    Write-Host 'RESULT: PASS - the game loader parses both shipped members correctly'
} else {
    Write-Host 'RESULT: FAIL - see the probe output above'
}
exit $probeCode

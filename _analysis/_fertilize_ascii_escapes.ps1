# Does the OpenStep reader handle non-ASCII via \U escapes, and how small is it?
#
# Previous result: the braced OpenStep form parses, but UTF-8 bytes come through
# as Latin-1 mojibake (" %@æ\u{96}½..."), because the ASCII reader maps bytes
# 1:1 to chars.  OpenStep supports \Uxxxx escapes, so test that, and measure the
# deflated size against the 189-byte slot.
#
# ASCII only.
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

$exe = Join-Path $env:CARGO_TARGET_DIR 'debug\plisttest.exe'
if (-not (Test-Path $exe)) { Write-Host "FAIL: probe not built; run _fertilize_ascii_check.ps1 first"; exit 1 }

$dir = Join-Path $env:TEMP ('plistesc_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $dir | Out-Null

# The 8 values, as \U escapes (UTF-16 code units, uppercase hex).
$pairs = @(
    @{ K = 'Cupid Zombie';        U = '\U4E18\U6BD4\U7279\U50F5\U5C38' },  # 丘比特僵尸
    @{ K = 'Fertilized by %@!';   U = ' %@\U65BD\U80A5\U4E86' },          # ' %@施肥了'
    @{ K = 'Flower Zombie';       U = '\U82B1\U82B1\U50F5\U5C38' },       # 花花僵尸
    @{ K = 'Garden Zombie';       U = '\U56ED\U4E01\U50F5\U5C38' },       # 园丁僵尸
    @{ K = 'Green Flower Zombie'; U = '\U82B1\U82B1\U50F5\U5C38' },       # 花花僵尸
    @{ K = 'ZomBotanist';         U = '\U751F\U6001\U50F5\U5C38' },       # 生态僵尸
    @{ K = 'Zombee';              U = '\U871C\U8702\U50F5\U5C38' },       # 蜜蜂僵尸
    @{ K = 'Zombutterfly';        U = '\U8774\U8776\U50F5\U5C38' }        # 蝴蝶僵尸
)
$lines = @('{')
foreach ($p in $pairs) { $lines += ('  "{0}" = "{1}";' -f $p.K, $p.U) }
$lines += '}'
$text = ($lines -join "`n") + "`n"
$path = Join-Path $dir 'escaped.strings'
[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))

Write-Host '== OpenStep with \U escapes =='
$out = & $exe $path 2>&1
$out | ForEach-Object { Write-Host "  $_" }
$ok = ($out -join "`n") -match 'PARSED OK'

Write-Host ''
Write-Host '== sizes (slot is 189 bytes compressed) =='
$raw = [System.IO.File]::ReadAllBytes($path)
Write-Host ("  raw text            = {0} bytes" -f $raw.Length)
Add-Type -AssemblyName System.IO.Compression
foreach ($lvl in @([System.IO.Compression.CompressionLevel]::Optimal,
                   [System.IO.Compression.CompressionLevel]::Fastest,
                   [System.IO.Compression.CompressionLevel]::SmallestSize)) {
    $ms = New-Object System.IO.MemoryStream
    $ds = New-Object System.IO.Compression.DeflateStream($ms, $lvl, $true)
    $ds.Write($raw, 0, $raw.Length); $ds.Close()
    Write-Host ("  deflate {0,-13} = {1} bytes  {2}" -f $lvl, $ms.Length,
        $(if ($ms.Length -le 189) { 'FITS' } else { 'over by ' + ($ms.Length - 189) }))
    $ms.Dispose()
}

Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ''
if ($ok) { Write-Host 'RESULT: \U escapes parse correctly' } else { Write-Host 'RESULT: \U escapes did NOT parse' }
exit $(if ($ok) { 0 } else { 1 })

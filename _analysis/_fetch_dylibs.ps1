# Fetch the two dylibs that trunk-era touchHLE loads but this project's
# touchHLE_dylibs/ folder predates:
#   libxml2.2.dylib       (from touchHLE/libxml2-dylib  v0.1.1)
#   libsqlite.3.6.10.dylib(from touchHLE/sqlite-dylib   v0.1.2)
#
# Without them touchHLE panics in fs.rs handle_open_err() because the guest
# filesystem lists the dylib as present but the host file is missing.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$root = (Split-Path -Parent $PSScriptRoot)
# The emulator lives in its own folder now (the tree mirrors the shipped
# ./Release layout). Fall back to the flat layout so these scripts keep working
# either way -- same rule GameManager.ps1 uses.
$hleRoot = if (Test-Path -LiteralPath (Join-Path $root 'touchHLE\touchHLE.exe')) {
    Join-Path $root 'touchHLE'
} else {
    $root
}

$dst  = Join-Path $hleRoot 'touchHLE_dylibs'
$log  = Join-Path $root '_analysis\_dylib_fetch.log'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}
Set-Content -LiteralPath $log -Value "dylib fetch started $(Get-Date -Format o)" -Encoding utf8

$items = @(
    @{ name='libxml2.2.dylib';        url='https://github.com/touchHLE/libxml2-dylib/releases/download/v0.1.1/libxml2.2.dylib';        sha='' },
    @{ name='libsqlite.3.6.10.dylib'; url='https://github.com/touchHLE/sqlite-dylib/releases/download/v0.1.2/libsqlite.3.6.10.dylib'; sha='' }
)

foreach ($it in $items) {
    $target = Join-Path $dst $it.name
    if (Test-Path $target) {
        Log "already present: $($it.name)  ($((Get-Item $target).Length) bytes)"
        continue
    }
    Log "downloading $($it.name) ..."
    try {
        Invoke-WebRequest -Uri $it.url -OutFile $target -UseBasicParsing -TimeoutSec 600
        $len = (Get-Item $target).Length
        $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        Log "  ok: $len bytes  sha256=$hash"
    } catch {
        Log "  FAILED: $($_.Exception.Message)"
    }
}

Log '--- touchHLE_dylibs now ---'
Get-ChildItem $dst | Select-Object Name,Length | ForEach-Object { Log ("  {0,-28} {1}" -f $_.Name, $_.Length) }
Log 'dylib fetch DONE'

# Restore the fork's build dependencies after touchHLE-trunk was removed.
#
# History: the fork's vendor/{stb,boost,openal-soft,SDL} were NTFS *junctions*
# pointing into touchHLE-trunk\vendor (created by _build_fork.ps1, which reused
# the trunk's pinned checkouts instead of re-downloading them). Deleting the
# trunk therefore broke the build with:
#     lib.c(12): fatal error C1083: cannot open ../../../vendor/stb/stb_image.h
#
# This script repopulates those four directories as REAL directories inside the
# fork, so the fork no longer depends on the trunk at all. It reuses the cached
# boost tarball and clones the same upstream commits the trunk had pinned.
#
# Idempotent: a directory that already has content is left alone.
#
# ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'

$hleRoot = Join-Path $Root 'touchHLE'
$fork    = Join-Path $hleRoot 'touchHLE-fork'
$vendor  = Join-Path $fork 'vendor'
$log     = Join-Path $Root '_analysis\_vendor_restore.log'

function Log([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}

function Run([string]$exe, [string[]]$argv, [string]$tag) {
    $tmp = Join-Path $env:TEMP "vendor_restore_$tag.out"
    & $exe @argv *> $tmp
    $code = $LASTEXITCODE
    if (Test-Path $tmp) {
        Get-Content -LiteralPath $tmp -Tail 4 -ErrorAction SilentlyContinue |
            ForEach-Object { Log "    | $_" }
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
    Log "  $exe $($argv -join ' ')  => exit=$code"
    return $code
}

function FileCount([string]$dir) {
    if (-not (Test-Path -LiteralPath $dir)) { return -1 }
    return (Get-ChildItem -LiteralPath $dir -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object).Count
}

function Remove-IfDeadLink([string]$dir) {
    # A junction whose target no longer exists is invisible to Test-Path, so
    # check the link itself as well.
    $item = Get-Item -LiteralPath $dir -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) { return }
    if ((FileCount $dir) -le 0) {
        Log "removing stale link/empty dir: $dir"
        cmd /c rmdir "$dir" 2>&1 | Out-Null
    }
}

Set-Content -LiteralPath $log -Value "vendor restore started $(Get-Date -Format o)" -Encoding utf8
$env:GIT_TERMINAL_PROMPT = '0'
New-Item -ItemType Directory -Force -Path $vendor | Out-Null

# --- 1. stb (header-only; the one that actually broke the build) ----------
$stb = Join-Path $vendor 'stb'
Remove-IfDeadLink $stb
if ((FileCount $stb) -gt 0) {
    Log "skip (populated): stb"
} else {
    [void](Run 'git' @('-c','advice.detachedHead=false','clone','--depth','1','--branch','dev',
                       'https://github.com/nothings/stb.git', $stb) 'stb')
}
Log ("stb stb_image.h present: {0}" -f (Test-Path (Join-Path $stb 'stb_image.h')))

# --- 2. openal-soft -------------------------------------------------------
$oal = Join-Path $vendor 'openal-soft'
Remove-IfDeadLink $oal
if ((FileCount $oal) -gt 0) {
    Log "skip (populated): openal-soft"
} else {
    [void](Run 'git' @('-c','advice.detachedHead=false','clone','--depth','1',
                       'https://github.com/kcat/openal-soft', $oal) 'openal')
}

# --- 3. SDL, pinned to the commit the trunk used --------------------------
$sdl = Join-Path $vendor 'SDL'
$sdlSha = '07d0f51fa292895443f563f0cbde4cb3802d87fa'
Remove-IfDeadLink $sdl
if ((FileCount $sdl) -gt 0) {
    Log "skip (populated): SDL"
} else {
    New-Item -ItemType Directory -Force -Path $sdl | Out-Null
    Push-Location $sdl
    try {
        [void](Run 'git' @('init','-q') 'sdl_init')
        [void](Run 'git' @('remote','add','origin','https://github.com/libsdl-org/SDL.git') 'sdl_remote')
        [void](Run 'git' @('fetch','--depth','1','origin',$sdlSha) 'sdl_fetch')
        [void](Run 'git' @('checkout','-q','FETCH_HEAD') 'sdl_co')
    } finally { Pop-Location }
}

# --- 4. boost, from the cached tarball if possible ------------------------
$boost = Join-Path $vendor 'boost'
Remove-IfDeadLink $boost
if ((FileCount $boost) -gt 0) {
    Log "skip (populated): boost"
} else {
    $tgz = Join-Path $hleRoot '_build_tools\downloads\boost_1_81_0.tar.gz'
    if (-not (Test-Path -LiteralPath $tgz)) {
        $dl = Split-Path $tgz -Parent
        New-Item -ItemType Directory -Force -Path $dl | Out-Null
        Log "downloading boost 1.81.0 ..."
        try {
            Invoke-WebRequest -Uri 'https://archives.boost.io/release/1.81.0/source/boost_1_81_0.tar.gz' `
                -OutFile $tgz -UseBasicParsing -TimeoutSec 1800
        } catch { Log "boost download FAILED: $($_.Exception.Message)" }
    }
    if (Test-Path -LiteralPath $tgz) {
        Log "boost tarball: $((Get-Item $tgz).Length) bytes"
        [void](Run 'tar.exe' @('-xzf', $tgz, '-C', $vendor) 'boost_tar')
        $extracted = Join-Path $vendor 'boost_1_81_0'
        if (Test-Path -LiteralPath $extracted) {
            if (Test-Path -LiteralPath $boost) { cmd /c rmdir "$boost" 2>&1 | Out-Null }
            Move-Item -LiteralPath $extracted -Destination $boost
        }
    } else {
        Log "boost tarball unavailable - dynarmic build will fail"
    }
}

# --- report ---------------------------------------------------------------
Log '--- vendor state (all must be real, populated directories) ---'
foreach ($d in @('stb','boost','openal-soft','SDL','dynarmic','PVRTDecompress')) {
    $p = Join-Path $vendor $d
    $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
    $lt = if ($item -and $item.LinkType) { $item.LinkType } else { 'real' }
    Log ("  {0,-14} link={1,-8} files={2}" -f $d, $lt, (FileCount $p))
}
Log 'vendor restore DONE'

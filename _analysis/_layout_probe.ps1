# Confirm empirically that touchHLE resolves its resources from the CURRENT
# DIRECTORY rather than from the executable's location.
#
# Why this matters for the requested layout change: if resources are found relative
# to the exe, then moving touchHLE.exe into a "touchHLE" subfolder keeps working
# automatically. If they are found relative to the cwd (which is what
# src/paths.rs suggests -- user_data_base_path() returns Path::new(".") on
# Windows), then the launcher MUST set the working directory to that subfolder, or
# touchHLE will fail to find its dylibs.
#
# The test builds a scratch copy of the bundle with the resources in a subfolder and
# launches it with the cwd set to that subfolder, then checks whether it reaches
# gameplay.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$Seconds = 30
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'

$release = Join-Path $Root 'Release'
$scratch = Join-Path $env:TEMP ('hle_layout_' + [Guid]::NewGuid().ToString('N'))
$sub = Join-Path $scratch 'touchHLE'

Write-Host "scratch: $scratch"
New-Item -ItemType Directory -Force -Path $sub | Out-Null

# Lay it out the way the user asked: touchHLE files in a subfolder.
foreach ($item in @('touchHLE.exe', 'touchHLE_dylibs', 'touchHLE_fonts',
                    'touchHLE_sandbox', 'touchHLE_options.txt',
                    'touchHLE_default_options.txt')) {
    $src = Join-Path $release $item
    if (-not (Test-Path -LiteralPath $src)) { Write-Host "  missing in Release: $item"; exit 1 }
    Copy-Item -LiteralPath $src -Destination $sub -Recurse -Force
}
# The IPA stays outside, in its own folder, as requested.
$ipaDir = Join-Path $scratch 'zombie_farm_ipa'
New-Item -ItemType Directory -Force -Path $ipaDir | Out-Null
$ipa = Get-ChildItem (Join-Path $release 'zombie_farm_ipa') -Filter '*.ipa' | Select-Object -First 1
Copy-Item -LiteralPath $ipa.FullName -Destination $ipaDir

Write-Host 'layout:'
Get-ChildItem $scratch -Recurse -Depth 1 | ForEach-Object {
    Write-Host ("  " + $_.FullName.Replace("$scratch\", ''))
}

$log = Join-Path $Root '_analysis\perf\layout_cwd.log'
Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue

function Invoke-With {
    param([string]$Tag, [string]$WorkingDirectory)

    Write-Host ''
    Write-Host "--- $Tag (cwd = $WorkingDirectory) ---"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = Join-Path $sub 'touchHLE.exe'
    $psi.Arguments = '"' + (Join-Path $ipaDir $ipa.Name) + '" --landscape-right'
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $env:TOUCHHLE_TIME_OFFSET_SECONDS = '0'
    $proc = [System.Diagnostics.Process]::Start($psi)

    Start-Sleep -Seconds $Seconds
    $alive = -not $proc.HasExited

    if ($alive) {
        Get-Process -Name 'touchHLE' -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }
    $out = ''; $err = ''
    try { $out = $proc.StandardOutput.ReadToEnd() } catch { }
    try { $err = $proc.StandardError.ReadToEnd() } catch { }
    if (-not $proc.HasExited) { try { [void]$proc.WaitForExit(10000) } catch { } }

    $text = $out + "`n" + $err
    Add-Content -LiteralPath $log -Value "===== $Tag =====" -Encoding UTF8
    Add-Content -LiteralPath $log -Value $text -Encoding UTF8

    $began = $text -match 'CPU emulation begins'
    $panic = ($text -split "`r?`n") | Select-String -Pattern 'panicked|assertion failed|Unexpected I/O failure' |
        Select-Object -First 2

    Write-Host ("  still running: {0}" -f $alive)
    Write-Host ("  reached gameplay: {0}" -f $(if ($began) { 'YES' } else { 'no' }))
    if ($panic) {
        foreach ($p in $panic) { Write-Host "  error: $($p.Line.Trim())" }
    }

    Start-Sleep -Seconds 3
    return ($alive -and $began)
}

# Case A: cwd set to the subfolder (the launcher would have to do this).
$okA = Invoke-With -Tag 'A: cwd = touchHLE subfolder' -WorkingDirectory $sub

# Case B: cwd left at the parent -- if resources resolve from the exe, this also works.
$okB = Invoke-With -Tag 'B: cwd = parent folder' -WorkingDirectory $scratch

Write-Host ''
Write-Host '=== conclusion ==='
if ($okA) {
    Write-Host 'A works: resources resolve from the CURRENT DIRECTORY.'
    Write-Host '  => the subfolder layout is fine, but the launcher MUST set cwd there.'
} else {
    Write-Host 'A failed: the subfolder layout needs more than a cwd change.'
}
if ($okB) {
    Write-Host 'B also works: resources resolve from the EXECUTABLE location, so cwd does not matter.'
} else {
    Write-Host 'B failed: confirms resources do NOT resolve from the executable location.'
}

Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ''
Write-Host ("RESULT: " + $(if ($okA) { 'PASS - subfolder layout is viable' } else { 'FAIL' }))
exit $(if ($okA) { 0 } else { 1 })

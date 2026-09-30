# Restore this project's deleted SAVE BACKUPS from the recycle bin.
#
# Why not the obvious approaches:
#   * Shell.Application's "restore" verb works but drives the Explorer UI and hung
#     a non-interactive session.
#   * The $I metadata's stored original path is TRUNCATED for long paths, so it
#     cannot be used to rebuild the destination.
#
# Instead, each $R file is identified by content (version-14 header plus the
# UNDEFINED marker) and named from the recycle bin's own naming rule:
#     $R<6 random chars><original extension>
# so "$R4U49GU.bak"               was "saveGame.bin2.bak"
#    "$R9XSNPT.bak-2026...-pre"   was "saveGame.bin2.bak-2026...-pre"
# Only files whose suffix is ".bak" or ".bak-..." are restored, i.e. backups. A
# plain "saveGame.bin2" is deliberately left alone: the live save has since been
# rewritten by the game itself and is newer than anything in the bin.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Target = "$root\touchHLE_sandbox\com.playforge.ZombieFarm.ZFR\Documents",
    [datetime]$DeletedAfter = [datetime]'2026-09-19 20:00',
    [switch]$ListOnly,
    [switch]$Overwrite
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'

$sid = (Get-ChildItem 'C:\$Recycle.Bin' -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { (Get-ChildItem $_.FullName -File -Force -Filter '$R*' -ErrorAction SilentlyContinue) } |
    Select-Object -First 1).FullName
if (-not $sid) { throw 'Could not locate the recycle bin backing store.' }
Write-Host "recycle bin: $sid"
if (-not (Test-Path -LiteralPath $Target)) { throw "Target folder missing: $Target" }

$marker = [byte[]]@(0x01,0x09,0x00,0x00,0x00,0x55,0x4E,0x44,0x45,0x46,0x49,0x4E,0x45,0x44)

function Test-IsZfrSave {
    param([byte[]]$Data)
    if ($Data.Length -lt 100 -or $Data.Length -gt 20000) { return $false }
    if ([BitConverter]::ToInt32($Data, 0) -ne 14) { return $false }
    for ($i = 0; $i -le $Data.Length - $marker.Length; $i++) {
        if ($Data[$i] -ne $marker[0]) { continue }
        $ok = $true
        for ($j = 1; $j -lt $marker.Length; $j++) {
            if ($Data[$i + $j] -ne $marker[$j]) { $ok = $false; break }
        }
        if ($ok) { return $true }
    }
    return $false
}

$candidates = @()
foreach ($r in (Get-ChildItem $sid -File -Force -Filter '$R*' -ErrorAction SilentlyContinue)) {
    if ($r.Length -lt 100 -or $r.Length -gt 20000) { continue }

    # "<6 random chars>.<extension>"; only backups are restored.
    $tail = $r.Name.Substring(2)
    $dot = $tail.IndexOf('.')
    if ($dot -lt 0) { continue }
    $name = 'saveGame.bin2' + $tail.Substring($dot)
    if ($name -notlike 'saveGame.bin2.bak*') { continue }

    $deleted = $null
    $iFile = Join-Path $sid ($r.Name -replace '^\$R', '$I')
    if (Test-Path -LiteralPath $iFile) {
        $ib = [System.IO.File]::ReadAllBytes($iFile)
        if ($ib.Length -ge 24) {
            try { $deleted = [DateTime]::FromFileTime([BitConverter]::ToInt64($ib, 16)) } catch { }
        }
    }
    if ($null -eq $deleted -or $deleted -lt $DeletedAfter) { continue }

    $data = [System.IO.File]::ReadAllBytes($r.FullName)
    if (-not (Test-IsZfrSave -Data $data)) { continue }

    $candidates += [pscustomobject]@{
        Content = $r.FullName
        Name    = $name
        Size    = $r.Length
        Deleted = $deleted
        Dest    = Join-Path $Target $name
    }
}

# If the same name appears more than once, keep the most recently deleted copy.
$unique = @{}
foreach ($c in ($candidates | Sort-Object Deleted)) { $unique[$c.Name] = $c }
$candidates = @($unique.Values | Sort-Object Name)

Write-Host "recoverable backups deleted after $($DeletedAfter.ToString('MM-dd HH:mm')): $($candidates.Count)"
Write-Host ''
foreach ($c in $candidates) {
    $exists = if (Test-Path -LiteralPath $c.Dest) { 'EXISTS' } else { '      ' }
    Write-Host ("  {0,6} B  {1}  {2}" -f $c.Size, $exists, $c.Name)
}

if ($ListOnly) { exit 0 }

Write-Host ''
$restored = 0
$skipped = 0
foreach ($c in $candidates) {
    if ((Test-Path -LiteralPath $c.Dest) -and -not $Overwrite) { $skipped++; continue }
    Copy-Item -LiteralPath $c.Content -Destination $c.Dest -Force
    $restored++
}
Write-Host "restored: $restored   skipped (already present): $skipped"

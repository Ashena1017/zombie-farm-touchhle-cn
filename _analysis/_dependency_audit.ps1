# Verify exactly which other files GameManager.ps1 actually needs at runtime.
#
# Method: run its -SelfTest with the candidate helper scripts temporarily renamed
# away, one at a time, and see whether it still passes. That turns "I think it
# only needs X" into a measurement.
#
# Renaming rather than copying because a copy would leave the original in place
# and the test would prove nothing. Everything is restored in a finally block.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
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
$manager = Join-Path $Root 'GameManager.ps1'

# Candidates: every .ps1 in the root other than the manager itself.
$candidates = @(Get-ChildItem -LiteralPath $Root -Filter '*.ps1' -File |
    Where-Object { $_.Name -ne 'GameManager.ps1' } |
    Sort-Object Name)

Write-Host "candidates to hide: $($candidates.Count)"
foreach ($c in $candidates) { Write-Host "  $($c.Name)" }
Write-Host ''

# Baseline: does the self-test pass with everything present?
Write-Host '--- baseline (nothing hidden) ---'
$out = & powershell -NoProfile -ExecutionPolicy Bypass -File $manager -SelfTest 2>&1
$baseOk = ($out | Select-String 'SELFTEST: PASS').Count -gt 0
Write-Host ("  SELFTEST: " + $(if ($baseOk) { 'PASS' } else { 'FAIL' }))
if (-not $baseOk) {
    Write-Host 'baseline failed; aborting (the audit would be meaningless)'
    exit 1
}

Write-Host ''
Write-Host '--- hiding each script in turn ---'
$results = @()
foreach ($c in $candidates) {
    $hidden = "$($c.FullName).hidden-for-audit"
    $status = 'unknown'
    try {
        Move-Item -LiteralPath $c.FullName -Destination $hidden -Force
        $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $manager -SelfTest 2>&1
        $passed = ($out | Select-String 'SELFTEST: PASS').Count -gt 0
        $status = if ($passed) { 'not needed' } else { 'NEEDED' }
    } catch {
        $status = "error: $($_.Exception.Message)"
    } finally {
        if (Test-Path -LiteralPath $hidden) {
            Move-Item -LiteralPath $hidden -Destination $c.FullName -Force
        }
    }
    Write-Host ("  {0,-32} {1}" -f $c.Name, $status)
    $results += [pscustomobject]@{ Name = $c.Name; Status = $status }
}

# The settings file is not a script, so check it separately.
Write-Host ''
Write-Host '--- hiding touchHLE_options.txt ---'
$opt = Join-Path $hleRoot 'touchHLE_options.txt'
$optHidden = "$opt.hidden-for-audit"
try {
    Move-Item -LiteralPath $opt -Destination $optHidden -Force
    $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $manager -SelfTest 2>&1
    $passed = ($out | Select-String 'SELFTEST: PASS').Count -gt 0
    Write-Host ("  {0,-32} {1}" -f 'touchHLE_options.txt', $(if ($passed) { 'recreated if missing' } else { 'NEEDED' }))
} finally {
    if (Test-Path -LiteralPath $optHidden) {
        Remove-Item -LiteralPath $opt -Force -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $optHidden -Destination $opt -Force
    }
}

Write-Host ''
Write-Host '--- summary ---'
$needed = @($results | Where-Object { $_.Status -eq 'NEEDED' })
if ($needed.Count -eq 0) {
    Write-Host 'GameManager.ps1 needs NO other .ps1 to run its own features.' -ForegroundColor Green
} else {
    Write-Host 'Needed at runtime:' -ForegroundColor Yellow
    foreach ($n in $needed) { Write-Host "  $($n.Name)" }
}

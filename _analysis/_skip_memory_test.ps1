# Probe the new skip-memory helpers without launching the game or showing UI.
# Extracts Read-SkipMemory / Save-SkipMemory from GameManager.ps1 via the AST
# (same technique as the earlier currency probe), points SkipMemoryFile at a
# throwaway temp file, and checks round-trip + edge cases.
$gm = Join-Path (Split-Path -Parent $PSScriptRoot) 'GameManager.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $gm, [ref]$null, [ref]$null)
$wanted = @('Read-SkipMemory', 'Save-SkipMemory')
foreach ($fn in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($wanted -contains $fn.Name) { Invoke-Expression $fn.Extent.Text }
}

# Point the memory file at a temp location (the functions read $script:SkipMemoryFile).
$script:SkipMemoryFile = Join-Path $env:TEMP ('zf_skipmem_test_{0}.txt' -f [guid]::NewGuid().ToString('N'))

$fail = 0
function Check($name, $cond) {
    if ($cond) { Write-Host "  PASS  $name" } else { Write-Host "  FAIL  $name"; $script:fail++ }
}

# 1. No file -> $null
$m = Read-SkipMemory
Check 'absent file returns null' ($null -eq $m)

# 2. Round trip 6:15
Save-SkipMemory -Hours 6 -Minutes 15
$m = Read-SkipMemory
Check 'round-trip 6h15m' ($m.Hours -eq 6 -and $m.Minutes -eq 15)

# 3. Round trip 0:07 (zero hours, padded minutes)
Save-SkipMemory -Hours 0 -Minutes 7
$m = Read-SkipMemory
Check 'round-trip 0h07m' ($m.Hours -eq 0 -and $m.Minutes -eq 7)

# 4. Large hours
Save-SkipMemory -Hours 1234 -Minutes 59
$m = Read-SkipMemory
Check 'round-trip 1234h59m' ($m.Hours -eq 1234 -and $m.Minutes -eq 59)

# 5. Corrupt content -> $null (no throw)
[System.IO.File]::WriteAllText($script:SkipMemoryFile, 'not a duration')
$m = Read-SkipMemory
Check 'garbage returns null' ($null -eq $m)

# 6. Out-of-range minutes in file -> $null
[System.IO.File]::WriteAllText($script:SkipMemoryFile, '6:99')
$m = Read-SkipMemory
Check 'minutes>59 returns null' ($null -eq $m)

Remove-Item -LiteralPath $script:SkipMemoryFile -Force -ErrorAction SilentlyContinue
Write-Host ''
if ($fail) { Write-Host "RESULT: FAIL ($fail)"; exit 1 } else { Write-Host 'RESULT: PASS' }

# Ensure every PowerShell script with non-ASCII content is saved as UTF-8 *with*
# a BOM, then syntax-check all of them.
#
# Why this is needed: Windows PowerShell 5.1 decodes a .ps1 that has no BOM using
# the console's ANSI code page (GBK on this machine). Chinese text inside single
# quotes then decodes to bytes that can include 0x27, which terminates the string
# early and produces a cascade of bogus parse errors. The `edit` tool rewrites
# files without a BOM, so this must be re-run after editing any such script.
#
# Run after any edit:  .\scripts\_ensure_bom.ps1
#
# Checks source directories and skips generated files and vendored code.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$fixed = 0
$failed = 0

# Prune unrelated trees before enumerating files. Build outputs and historical
# fixtures can contain old or deliberately broken copies of the scripts.
$skipDirectories = @('vendor', 'target', 'target-fork', '_build_tools',
                     'archive', 'dumps', 'perf', 'run', 'dist', 'Release',
                     'touchHLE-zombiefarm-android-arm64')
function Get-Scripts([string]$Path) {
    Get-ChildItem -LiteralPath $Path -Filter '*.ps1' -File
    foreach ($dir in (Get-ChildItem -LiteralPath $Path -Directory)) {
        if ($dir.Name -in $skipDirectories -or $dir.Name.StartsWith('.') -or
            ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
        Get-Scripts $dir.FullName
    }
}

$files = @(Get-Scripts $Root | Sort-Object FullName)

Write-Host "Checking $($files.Count) PowerShell script(s) under $Root"
Write-Host ''

foreach ($file in $files) {
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    $nonAscii = 0
    foreach ($b in $bytes) { if ($b -gt 127) { $nonAscii++ } }

    # Show the path relative to the root so subdirectory files are identifiable.
    $rel = $file.FullName.Substring($Root.Length).TrimStart('\')

    if ($nonAscii -gt 0 -and -not $hasBom) {
        if ($CheckOnly) {
            Write-Host ("  MISSING BOM  {0}  ({1} non-ASCII bytes)" -f $rel, $nonAscii) -ForegroundColor Red
            $failed++
            continue
        }
        $text = [System.IO.File]::ReadAllText($file.FullName, $utf8NoBom)
        [System.IO.File]::WriteAllText($file.FullName, $text, $utf8Bom)
        Write-Host ("  fixed BOM    {0}" -f $rel) -ForegroundColor Yellow
        $fixed++
    } elseif ($nonAscii -gt 0) {
        Write-Host ("  ok (BOM)     {0}" -f $rel) -ForegroundColor DarkGray
    } else {
        Write-Host ("  ok (ASCII)   {0}" -f $rel) -ForegroundColor DarkGray
    }
}

Write-Host ''
Write-Host '--- syntax check ---'

# Parse each file with the real PowerShell parser, in a child process so the
# check itself is unaffected by the encoding of this script.
$checker = Join-Path $env:TEMP ('bomcheck_' + [Guid]::NewGuid().ToString('N') + '.ps1')
$listPath = [IO.Path]::ChangeExtension($checker, '.txt')
$checkBody = @'
$bad = 0
$root = $args[0]
foreach ($path in [IO.File]::ReadAllLines($args[1])) {
    $errs = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile(
        $path, [ref]$null, [ref]$errs)
    $rel = $path.Substring($root.Length).TrimStart('\')
    if ($errs -and $errs.Count) {
        Write-Host ("  FAIL  {0}" -f $rel)
        $errs | Select-Object -First 4 | ForEach-Object {
            Write-Host ("          line {0}: {1}" -f $_.Extent.StartLineNumber, $_.Message)
        }
        $bad++
    } else {
        Write-Host ("  ok    {0}" -f $rel)
    }
}
exit $bad
'@
try {
    Set-Content -LiteralPath $checker -Value $checkBody -Encoding utf8
    [IO.File]::WriteAllLines($listPath, [string[]]@($files.FullName), $utf8Bom)
    & powershell -NoProfile -ExecutionPolicy Bypass -File $checker $Root $listPath
    $badCount = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $checker, $listPath -Force -ErrorAction SilentlyContinue
}

Write-Host ''
if ($badCount -ne 0 -or $failed -ne 0) {
    Write-Host "RESULT: $badCount file(s) with syntax errors, $failed missing BOM" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: all scripts parse; $fixed file(s) had their BOM restored" -ForegroundColor Green

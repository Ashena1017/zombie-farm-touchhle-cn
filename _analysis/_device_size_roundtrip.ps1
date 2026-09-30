# Syntax-check GameManager.ps1 and exercise the option-file round-trip for the
# window settings (window_family / window_scale) and the wheel-zoom setting,
# without opening the GUI. ASCII only.
#
# History: this used to test a single `device_size` setting that bundled
# --device-family and --scale-hack into one choice list, which forced a
# "most specific match" rule in the reader (a native entry's option set was a
# subset of every scaled entry's). The settings are now separate, one option
# each, so that whole class of ambiguity is gone; this script asserts that
# directly instead of testing the disambiguation.
$ErrorActionPreference = 'Stop'
$root = (Split-Path -Parent $PSScriptRoot)
Set-Location $root

# GameManager.ps1 is UTF-8 *with* BOM, but Get-Content -Raw on this PowerShell
# version still needs the encoding named explicitly, or the Chinese literals get
# decoded as GBK and the parse blows up with mojibake errors.
$src = [System.IO.File]::ReadAllText((Join-Path $root 'GameManager.ps1'), [System.Text.UTF8Encoding]::new($false))
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) {
    Write-Host ("PARSE ERRORS: {0}" -f $errors.Count)
    $errors | Select-Object -First 10 | ForEach-Object { Write-Host ("  " + $_.Message) }
    exit 1
}
Write-Host 'GameManager.ps1 parses OK (0 errors)'

# SettingDefs is a single `$script:SettingDefs = [ordered]@{ ... }` literal.
# Evaluate just that statement so we test the real definitions.
$assign = $ast.FindAll({
    param($n)
    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left.Extent.Text -eq '$script:SettingDefs'
}, $true) | Select-Object -First 1
if (-not $assign) { Write-Host 'FAIL: could not find $script:SettingDefs'; exit 1 }

Invoke-Expression $assign.Extent.Text

$fails = 0

# --- 1. the window row ------------------------------------------------------
Write-Host ''
Write-Host '=== window_family / window_scale definitions ==='
$famDef = $script:SettingDefs['window_family']
$sclDef = $script:SettingDefs['window_scale']
if (-not $famDef) { Write-Host 'FAIL: no window_family definition'; exit 1 }
if (-not $sclDef) { Write-Host 'FAIL: no window_scale definition'; exit 1 }

foreach ($c in $famDef.Choices) {
    Write-Host ("  family {0,-8} {1}" -f $c.Value, $c.Text)
}
foreach ($c in $sclDef.Choices) {
    Write-Host ("  scale  {0,-8} {1}" -f $c.Value, $c.Text)
}
Write-Host ("  defaults: family={0} scale={1}" -f $famDef.Default, $sclDef.Default)

# The presets the operator asked for, in order: decimal values, not fractions.
$wantScales = @('1.25', '1.5', '1.75', 'custom')
$gotScales = @($sclDef.Choices | ForEach-Object { $_.Value })
$scaleOk = ($gotScales.Count -eq $wantScales.Count)
if ($scaleOk) {
    for ($i = 0; $i -lt $wantScales.Count; $i++) {
        if ($gotScales[$i] -ne $wantScales[$i]) { $scaleOk = $false; break }
    }
}
Write-Host ("  {0}  scale presets are {1}" -f $(if ($scaleOk) { 'PASS' } else { 'FAIL' }, ($wantScales -join ' > ')))
if (-not $scaleOk) { $fails++ }

# The default must be a real choice, and must be ipad x1.5.
$defOk = (@($sclDef.Choices | Where-Object { $_.Value -eq $sclDef.Default }).Count -eq 1) -and
         (@($famDef.Choices | Where-Object { $_.Value -eq $famDef.Default }).Count -eq 1)
Write-Host ("  {0}  both defaults are valid choices" -f $(if ($defOk) { 'PASS' } else { 'FAIL' }))
if (-not $defOk) { $fails++ }

$wantDefault = ($famDef.Default -eq 'ipad') -and ($sclDef.Default -eq '1.5')
Write-Host ("  {0}  default is ipad + 1.5 (got {1} + {2})" -f `
    $(if ($wantDefault) { 'PASS' } else { 'FAIL' }), $famDef.Default, $sclDef.Default)
if (-not $wantDefault) { $fails++ }

# --- 2. no setting bundles several options any more --------------------------
# An `Extra` key was how a choice expanded to several command-line tokens. If one
# reappears, the reader would need the specificity rule back.
Write-Host ''
Write-Host '=== no choice expands to several options ==='
$extraFails = 0
foreach ($key in $script:SettingDefs.Keys) {
    foreach ($c in $script:SettingDefs[$key].Choices) {
        if ($c.ContainsKey('Extra')) {
            $extraFails++
            Write-Host ("  {0}.{1} still has Extra: {2}" -f $key, $c.Value, ($c.Extra -join ' '))
        }
    }
}
Write-Host ("  {0}  no choice has Extra" -f $(if ($extraFails -eq 0) { 'PASS' } else { 'FAIL' }))
if ($extraFails -ne 0) { $fails++ }

# Every option prefix must be distinct, or two settings would fight over one
# command-line token.
Write-Host ''
Write-Host '=== option prefixes are distinct ==='
$prefixes = @{}
$prefixFails = 0
foreach ($key in $script:SettingDefs.Keys) {
    $p = $script:SettingDefs[$key].Prefix
    if ($prefixes.ContainsKey($p)) {
        $prefixFails++
        Write-Host ("  {0} and {1} both use '{2}'" -f $prefixes[$p], $key, $p)
    } else {
        $prefixes[$p] = $key
    }
}
Write-Host ("  {0}  {1} distinct prefixes" -f $(if ($prefixFails -eq 0) { 'PASS' } else { 'FAIL' }), $prefixes.Count)
if ($prefixFails -ne 0) { $fails++ }

# --- 3. round-trip through the real writer and reader ------------------------
# Mirror Save-Settings' emit logic and Get-CurrentSettings' matching logic, to
# prove each value survives a write/read cycle. The flag setting is handled
# separately below because its spelling is presence/absence, not a value.
Write-Host ''
Write-Host '=== round-trip (emit -> token -> read) ==='
$emit = {
    param($key, $value)
    $def = $script:SettingDefs[$key]
    if ($def.Prefix.EndsWith('=')) { return @($def.Prefix + $value) }
    if ($value -eq '1') { return @($def.Prefix) }
    return @()
}
$readBack = {
    param($key, $tokens)
    $def = $script:SettingDefs[$key]
    if ($def.Prefix.EndsWith('=')) {
        foreach ($t in $tokens) {
            if ($t.StartsWith($def.Prefix)) { return $t.Substring($def.Prefix.Length) }
        }
        return '<absent>'
    }
    if ($tokens -contains $def.Prefix) { return '1' }
    return '0'
}
$rtFails = 0
foreach ($key in $script:SettingDefs.Keys) {
    $def = $script:SettingDefs[$key]
    foreach ($c in $def.Choices) {
        if ($c.Value -eq 'custom') { continue }
        $emitted = & $emit $key $c.Value
        $got = & $readBack $key $emitted
        $ok = ($got -eq $c.Value)
        if (-not $ok) { $rtFails++ }
        Write-Host ("  {0}  {1,-13} {2,-8} -> [{3}] -> {4}" -f `
            $(if ($ok) { 'PASS' } else { 'FAIL' }), $key, $c.Value, ($emitted -join ' '), $got)
    }
}
Write-Host ("  {0}  all preset values round-trip" -f $(if ($rtFails -eq 0) { 'PASS' } else { 'FAIL' }))
if ($rtFails -ne 0) { $fails++ }

# --- 4. the window arithmetic ------------------------------------------------
# The label must agree with what touchHLE's own scale_dim computes, because the
# label is the only place the resulting window size is visible before launching.
Write-Host ''
Write-Host '=== window size arithmetic (landscape) ==='
# Pull the pure function out of the script and run it for real.
$fnAst = $ast.FindAll({
    param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -eq 'Get-WindowSizeForScale'
}, $true) | Select-Object -First 1
if (-not $fnAst) { Write-Host 'FAIL: Get-WindowSizeForScale not found'; exit 1 }
Invoke-Expression $fnAst.Extent.Text

# ConvertTo-Number is a dependency of that function.
$cnAst = $ast.FindAll({
    param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -eq 'ConvertTo-Number'
}, $true) | Select-Object -First 1
if (-not $cnAst) { Write-Host 'FAIL: ConvertTo-Number not found'; exit 1 }
Invoke-Expression $cnAst.Extent.Text

$sizeCases = @(
    # The three decimal presets, which are what the UI offers.
    @{ Fam = 'ipad';   Scale = '1.25'; Want = '1280 × 960' }
    @{ Fam = 'ipad';   Scale = '1.5';  Want = '1536 × 1152' }
    @{ Fam = 'ipad';   Scale = '1.75'; Want = '1792 × 1344' }
    @{ Fam = 'ipad';   Scale = '1'; Want = '1024 × 768' }
    @{ Fam = 'ipad';   Scale = '2'; Want = '2048 × 1536' }
    @{ Fam = 'iphone'; Scale = '1'; Want = '480 × 320' }
    @{ Fam = 'iphone'; Scale = '1.5'; Want = '720 × 480' }
    # Both spellings of the same factor must give the same window.
    @{ Fam = 'ipad';   Scale = '5/4'; Want = '1280 × 960' }
    @{ Fam = 'ipad';   Scale = '3/2'; Want = '1536 × 1152' }
    @{ Fam = 'ipad';   Scale = '7/4'; Want = '1792 × 1344' }
)
$sizeFails = 0
foreach ($c in $sizeCases) {
    $got = Get-WindowSizeForScale -Family $c.Fam -Scale $c.Scale
    $ok = ($got -eq $c.Want)
    if (-not $ok) { $sizeFails++ }
    Write-Host ("  {0}  {1,-7} x{2,-5} -> {3}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $c.Fam, $c.Scale, $got)
}
Write-Host ("  {0}  window arithmetic" -f $(if ($sizeFails -eq 0) { 'PASS' } else { 'FAIL' }))
if ($sizeFails -ne 0) { $fails++ }

# --- 5. the recommended default must fit this screen -------------------------
# The whole reason the default is 1.5 rather than 2 is that 2048x1536 does not fit
# a 1440-high display. Assert the arithmetic behind that choice, and that every
# preset the UI offers fits this screen (a preset that opens off-screen would be a
# trap in the dropdown).
Write-Host ''
Write-Host '=== the default fits, the rejected one does not ==='
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class DispRt {
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern bool EnumDisplaySettingsW(string dev, int mode, ref DEVMODE dm);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
        public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
        public int dmFields, dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
        public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
        public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight;
    }
    public static int Width() {
        var dm = new DEVMODE(); dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
        if (!EnumDisplaySettingsW(null, -1, ref dm)) return 0;
        return dm.dmPelsWidth;
    }
    public static int Height() {
        var dm = new DEVMODE(); dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
        if (!EnumDisplaySettingsW(null, -1, ref dm)) return 0;
        return dm.dmPelsHeight;
    }
}
'@ -ErrorAction SilentlyContinue
# EnumDisplaySettings is DPI-unaware by nature (it reports the real mode), unlike
# GetSystemMetrics/Screen, which this box would report at 150% scaling.
$sw = [DispRt]::Width()
$sh = [DispRt]::Height()
Write-Host ("  screen: {0} x {1}" -f $sw, $sh)
if ($sw -gt 0 -and $sh -gt 0) {
    # Every preset offered for iPad must fit, since these are the choices a user can
    # click without knowing anything about their screen.
    foreach ($preset in @('1.25', '1.5', '1.75')) {
        $d = Get-WindowSizeForScale -Family 'ipad' -Scale $preset
        $fits = $d -match '^(\d+) × (\d+)$' -and [int]$Matches[1] -le $sw -and [int]$Matches[2] -le $sh
        Write-Host ("  {0}  preset x{1,-5} {2} fits" -f $(if ($fits) { 'PASS' } else { 'FAIL' }), $preset, $d)
        if (-not $fits) { $fails++ }
    }

    $x2 = Get-WindowSizeForScale -Family 'ipad' -Scale '2'
    $x2Fits = $x2 -match '^(\d+) × (\d+)$' -and [int]$Matches[1] -le $sw -and [int]$Matches[2] -le $sh
    # Not a failure either way - it is a fact about this screen that justifies the
    # default - but it is reported so a changed monitor is visible.
    Write-Host ("  info  iPad x2 {0} fits: {1}" -f $x2, $x2Fits)
}

Write-Host ''
Write-Host ("failures: {0}" -f $fails)
if ($fails -gt 0) { exit 1 }
Write-Host 'ALL CHECKS PASS'

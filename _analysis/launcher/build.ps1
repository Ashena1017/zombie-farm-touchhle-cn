# Compile the windowless launcher stub.
#
# 游戏管理.bat leaves a console window open for as long as the manager UI runs,
# because cmd.exe is a console program and a .bat cannot suppress that. This
# builds a tiny /target:winexe (subsystem 2 = GUI) program instead, so the UI
# starts with no black window at all.
#
# The output is a self-contained .exe requiring only .NET Framework 4.x, which is
# present on every supported Windows version. Launcher.cs is kept next to this
# script so the executable can be rebuilt from source at any time.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$src = Join-Path $PSScriptRoot 'Launcher.cs'
# Compile to an ASCII name first, then rename. csc.exe is a native program and
# receives its arguments through the ANSI code page, so passing a Chinese output
# path makes it write a file with a mangled name instead.
$tempOut = Join-Path $PSScriptRoot 'GameManagerLauncher.exe'
$out = Join-Path $root '游戏管理.exe'

$csc = Get-ChildItem 'C:\Windows\Microsoft.NET\Framework64' -Filter 'csc.exe' -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'v4\.' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1

if (-not $csc) { throw 'Could not find the .NET Framework 4.x C# compiler (csc.exe).' }
if (-not (Test-Path -LiteralPath $src)) { throw "Missing source: $src" }

Write-Host "compiler : $($csc.FullName)"

# /target:winexe sets the PE subsystem to 2 (Windows GUI), which is what prevents
# Windows from allocating a console for the process.
& $csc.FullName /nologo /target:winexe /optimize+ /platform:anycpu `
    "/out:$tempOut" `
    /reference:System.dll `
    /reference:System.Windows.Forms.dll `
    $src

if ($LASTEXITCODE -ne 0) { throw "csc failed with exit code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath $tempOut)) { throw "No output produced: $tempOut" }

# Rename via .NET so the Chinese name is applied as proper Unicode, not ANSI.
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Force }
[System.IO.File]::Move($tempOut, $out)

$item = Get-Item -LiteralPath $out
Write-Host "built    : $out  ($($item.Length) bytes)"

# Verify the subsystem really is GUI (2); a console (3) would defeat the purpose.
$bytes = [System.IO.File]::ReadAllBytes($out)
$peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
$subsystem = [BitConverter]::ToUInt16($bytes, $peOffset + 0x5C)
Write-Host "subsystem: $subsystem  ($(if ($subsystem -eq 2) { 'GUI - no console window' } else { 'CONSOLE - would still show a window!' }))"
if ($subsystem -ne 2) { throw 'Launcher was not built as a GUI subsystem executable.' }

Write-Host ''
Write-Host 'DONE'

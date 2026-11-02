# Capture the real title screen of the v29fix build (read-only probe; never touches Release\).
param(
    [string]$Ipa = '',
    [string]$Tag = 'title-full'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root 'Release\touchHLE'
$work = Join-Path $PSScriptRoot 'dumps\title-capture\run'
$outDir = Join-Path $PSScriptRoot 'dumps\title-capture'
if (-not $Ipa) {
    $Ipa = Join-Path $root 'Release\zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
if (-not (Test-Path (Join-Path $work 'touchHLE.exe'))) {
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    robocopy $src $work /E /NFL /NDL /NJH /NJS /NP | Out-Null
}

Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class W32 {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
# stay out of DPI virtualisation so GetWindowRect/PrintWindow use physical pixels
try { [void][W32]::SetProcessDpiAwarenessContext([IntPtr](-4)) } catch { [void][W32]::SetProcessDPIAware() }

$exe = Join-Path $work 'touchHLE.exe'
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $exe
$psi.Arguments = '"' + $Ipa + '" --landscape-right --no-error-popup'
$psi.WorkingDirectory = $work
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$proc = [System.Diagnostics.Process]::Start($psi)
Write-Output "started pid=$($proc.Id)"

$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { Write-Output "process exited code=$($proc.ExitCode)"; break }
    $proc.Refresh()
    if ($proc.MainWindowHandle -ne [IntPtr]::Zero) { $hwnd = $proc.MainWindowHandle; break }
}
Write-Output "hwnd=$hwnd"
if ($hwnd -eq [IntPtr]::Zero) { Write-Output 'NO WINDOW'; exit 2 }

# let the app finish loading the title screen
Start-Sleep -Seconds 25

$r = New-Object W32+RECT
[void][W32]::GetWindowRect($hwnd, [ref]$r)
$w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
Write-Output "rect=$($r.Left),$($r.Top) size=${w}x${h}"

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[void][W32]::PrintWindow($hwnd, $hdc, 2)   # PW_RENDERFULLCONTENT
$g.ReleaseHdc($hdc)
$g.Dispose()
$p1 = Join-Path $outDir ($Tag + '.png')
$bmp.Save($p1, [System.Drawing.Imaging.ImageFormat]::Png)

# mean luma of the interior; black usually means PrintWindow cannot see the GL surface
$sum = 0.0; $n = 0
for ($y = 40; $y -lt ($h - 40); $y += 7) {
    for ($x = 40; $x -lt ($w - 40); $x += 7) {
        $c = $bmp.GetPixel($x, $y)
        $sum += (0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B); $n++
    }
}
$luma = if ($n -gt 0) { $sum / $n } else { 0 }
Write-Output ("printwindow luma={0:N1}" -f $luma)
$bmp.Dispose()

if ($luma -lt 12) {
    Write-Output 'fallback: foreground + screen blit'
    [void][W32]::ShowWindow($hwnd, 3)
    [void][W32]::SetForegroundWindow($hwnd)
    Start-Sleep -Seconds 2
    [void][W32]::GetWindowRect($hwnd, [ref]$r)
    $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
    $bmp2 = New-Object System.Drawing.Bitmap($w, $h)
    $g2 = [System.Drawing.Graphics]::FromImage($bmp2)
    $g2.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $g2.Dispose()
    $p2 = Join-Path $outDir 'title-screen.png'
    $bmp2.Save($p2, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp2.Dispose()
    Write-Output "saved $p2"
} else {
    Write-Output "saved $p1"
}

if (-not $proc.HasExited) { $proc.Kill() }
Write-Output 'done'

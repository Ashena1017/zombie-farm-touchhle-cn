# Report the REAL desktop geometry, with DPI awareness enabled.
#
# Without SetProcessDPIAware(), Windows virtualizes the screen size for the
# process: on a 2560x1440 display at 150% scaling it reports 1707x960, which is
# what an earlier (wrong) measurement of this machine recorded. ASCII only.
$ErrorActionPreference = 'Continue'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class DpiProbe {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
    [DllImport("user32.dll")] public static extern bool SystemParametersInfo(uint uiAction, uint uiParam, out RECT pvParam, uint fWinIni);
    [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr hWnd);
    [DllImport("gdi32.dll")] public static extern int GetDeviceCaps(IntPtr hdc, int nIndex);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public const int SM_CXSCREEN = 0;
    public const int SM_CYSCREEN = 1;
    public const int LOGPIXELSX = 88;
    public const uint SPI_GETWORKAREA = 0x0030;

    public static int ScreenW() { return GetSystemMetrics(SM_CXSCREEN); }
    public static int ScreenH() { return GetSystemMetrics(SM_CYSCREEN); }
    public static int DpiX() { IntPtr dc = GetDC(IntPtr.Zero); int v = GetDeviceCaps(dc, LOGPIXELSX); return v; }
    public static RECT WorkArea() { RECT r; SystemParametersInfo(SPI_GETWORKAREA, 0, out r, 0); return r; }
}
'@ -ErrorAction SilentlyContinue

[void][DpiProbe]::SetProcessDPIAware()

$w = [DpiProbe]::ScreenW()
$h = [DpiProbe]::ScreenH()
$dpi = [DpiProbe]::DpiX()
$wa = New-Object DpiProbe+RECT
$wa = [DpiProbe]::WorkArea()

$scale = [Math]::Round($dpi / 96.0 * 100)

Write-Host '=== real desktop geometry (DPI aware) ==='
Write-Host ("  screen      : {0} x {1}" -f $w, $h)
Write-Host ("  work area   : {0} x {1}  (x={2}, y={3})" -f ($wa.Right - $wa.Left), ($wa.Bottom - $wa.Top), $wa.Left, $wa.Top)
Write-Host ("  DPI         : {0}  ({1}% scaling)" -f $dpi, $scale)
Write-Host ''
Write-Host '=== what a non-DPI-aware process would have seen ==='
Write-Host ("  {0} x {1}   (i.e. screen / {2})" -f [int]($w / ($dpi / 96.0)), [int]($h / ($dpi / 96.0)), ($dpi / 96.0))
Write-Host ''
Write-Host '=== does each resolution fit on screen? ==='
Write-Host '  (window = client area + ~16px border, ~39px title bar at this DPI)'
$workH = $wa.Bottom - $wa.Top
$workW = $wa.Right - $wa.Left
foreach ($r in @(@(1280,720), @(1600,900), @(1920,1080), @(2560,1440), @(1024,768), @(480,320))) {
    $cw = $r[0]; $ch = $r[1]
    $ow = $cw + 16
    $oh = $ch + 39
    $fitsW = $ow -le $workW
    $fitsH = $oh -le $workH
    $verdict = if ($fitsW -and $fitsH) { 'fits' } else { "TOO BIG (needs $ow x $oh)" }
    Write-Host ("  {0,5} x {1,-5} -> outer {2,5} x {3,-5}  {4}" -f $cw, $ch, $ow, $oh, $verdict)
}

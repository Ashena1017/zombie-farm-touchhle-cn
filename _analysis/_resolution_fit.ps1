# Measure the real window geometry for the 16:9 resolutions, DPI-aware, and
# report whether each fits the work area. ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$WaitSeconds = 40
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
$hleRoot = Join-Path $Root 'touchHLE'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class FitWin {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    public static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }
    public static int ScreenW() { return GetSystemMetrics(0); }
    public static int ScreenH() { return GetSystemMetrics(1); }
    public static IntPtr FindGameWindow(uint pid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (wpid == pid && IsWindowVisible(h) && !Cls(h).Contains("ConsoleWindowClass")) {
                RECT r; GetClientRect(h, out r);
                if ((r.Right - r.Left) > 100) { found = h; return false; }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@ -ErrorAction SilentlyContinue

[void][FitWin]::SetProcessDPIAware()
$sw = [FitWin]::ScreenW()
$sh = [FitWin]::ScreenH()
Write-Host ("desktop (DPI aware): {0} x {1}" -f $sw, $sh)
Write-Host ''

$ipa = Join-Path $Root 'zombie_farm_ipa\Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix.ipa'
$exe = Join-Path $hleRoot 'touchHLE.exe'

function Measure-One([string]$size, [string]$family = 'ipad') {
    $argv = @($ipa, "--device-family=$family", '--landscape-right', '--fps-limit=60')
    if ($size) { $argv += "--device-size=$size" }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ($argv | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $psi.WorkingDirectory = $hleRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)

    $hwnd = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { break }
        $hwnd = [FitWin]::FindGameWindow([uint32]$proc.Id)
    }

    $out = $null
    if ($hwnd -ne [IntPtr]::Zero) {
        Start-Sleep -Seconds 3
        $cr = New-Object FitWin+RECT; [void][FitWin]::GetClientRect($hwnd, [ref]$cr)
        $wr = New-Object FitWin+RECT; [void][FitWin]::GetWindowRect($hwnd, [ref]$wr)
        $out = @{
            CW = $cr.Right - $cr.Left; CH = $cr.Bottom - $cr.Top
            WL = $wr.Left; WT = $wr.Top
            WW = $wr.Right - $wr.Left; WH = $wr.Bottom - $wr.Top
        }
    }
    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
    Start-Sleep -Seconds 2
    return $out
}

Write-Host '=== window geometry per resolution (DPI aware) ==='
Write-Host ''
$rows = @()
foreach ($s in @('1080x720', '1350x900', '1620x1080', '2160x1440')) {
    $r = Measure-One $s
    if ($null -eq $r) { Write-Host ("  {0,-10} : window never appeared" -f $s); continue }
    $fitsW = ($r.WL -ge 0) -and (($r.WL + $r.WW) -le $sw)
    $fitsH = ($r.WT -ge 0) -and (($r.WT + $r.WH) -le $sh)
    $verdict = if ($fitsW -and $fitsH) { 'FITS' } else { 'CLIPPED' }
    Write-Host ("  {0,-10} : client {1}x{2}  outer {3}x{4} at ({5},{6})  {7}" -f `
        $s, $r.CW, $r.CH, $r.WW, $r.WH, $r.WL, $r.WT, $verdict)
    if (-not ($fitsW -and $fitsH)) {
        if (-not $fitsW) { Write-Host ("               width overflows by {0}px" -f (($r.WL + $r.WW) - $sw)) }
        if (-not $fitsH) { Write-Host ("               height overflows by {0}px" -f (($r.WT + $r.WH) - $sh)) }
    }
}

# The native device families must still produce their documented sizes, and must
# NOT be affected by the DPI change (they are the emulated screen, not the
# requested window size).
Write-Host ''
Write-Host '=== native device families (no --device-size) ==='
foreach ($c in @(@{ F = 'ipad';   E = @(1024, 768) },
                 @{ F = 'iphone'; E = @(480, 320) })) {
    $r = Measure-One $null $c.F
    if ($null -eq $r) { Write-Host ("  {0,-8} : window never appeared" -f $c.F); continue }
    $ok = ($r.CW -eq $c.E[0]) -and ($r.CH -eq $c.E[1])
    Write-Host ("  {0}  {1,-8} : client {2}x{3}  expected {4}x{5}" -f `
        $(if ($ok) {'PASS'} else {'FAIL'}), $c.F, $r.CW, $r.CH, $c.E[0], $c.E[1])
}

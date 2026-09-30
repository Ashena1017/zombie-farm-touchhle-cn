# Launch GameManager.ps1's GUI, wait for its window, screenshot it, then close it.
#
# The GUI is the deliverable, so "the script parses" is not enough evidence: this
# captures what the user will actually see. PrintWindow is used rather than a
# screen grab so the capture works even if the window is not on top.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OutFile = "$root\_analysis\gui.png",
    [int]$TimeoutSeconds = 40
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'

Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Drawing;
public class WinCap {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, System.Text.StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    // Find the first visible top-level window owned by the given process id.
    public static IntPtr FindWindowForPid(uint want) {
        IntPtr best = IntPtr.Zero;
        long bestArea = 0;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == want && IsWindowVisible(h)) {
                var sb = new System.Text.StringBuilder(512);
                GetWindowTextW(h, sb, 512);
                if (sb.Length > 0) {
                    RECT r; GetWindowRect(h, out r);
                    long area = (long)(r.Right - r.Left) * (r.Bottom - r.Top);
                    if (area > bestArea) { bestArea = area; best = h; }
                }
            }
            return true;
        }, IntPtr.Zero);
        return best;
    }
}
'@

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' +
    (Join-Path $Root 'GameManager.ps1') + '"'
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false

$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host "  launched pid=$($proc.Id)"

# The window belongs to a child PowerShell (the script runs in this process), so
# search by process id first and fall back to any window whose title matches.
$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    $hwnd = [WinCap]::FindWindowForPid([uint32]$proc.Id)
    if ($hwnd -eq [IntPtr]::Zero) {
        # The script may run the form on a nested process; look for the title.
        foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
            if ($p.MainWindowTitle -match 'Zombie Farm') {
                $hwnd = $p.MainWindowHandle
                if ($hwnd -ne [IntPtr]::Zero) { break }
            }
        }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}

if ($hwnd -eq [IntPtr]::Zero) {
    Write-Host '  FAIL: window never appeared'
    try { $proc.Kill() } catch { }
    exit 1
}

$sb = New-Object System.Text.StringBuilder 512
[void][WinCap]::GetWindowTextW($hwnd, $sb, 512)
Write-Host "  window : '$($sb.ToString())'  hwnd=$hwnd"

# Settle: the Shown handler loads settings and refreshes currency.
Start-Sleep -Seconds 3

$r = New-Object WinCap+RECT
[void][WinCap]::GetWindowRect($hwnd, [ref]$r)
$w = $r.Right - $r.Left
$h = $r.Bottom - $r.Top
Write-Host "  size   : ${w} x ${h}"

if ($w -le 0 -or $h -le 0) {
    Write-Host '  FAIL: zero-sized window'
    try { $proc.Kill() } catch { }
    exit 1
}

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $gfx.GetHdc()
# 2 == PW_RENDERFULLCONTENT, needed for windows drawn with modern compositing.
$okPrint = [WinCap]::PrintWindow($hwnd, $hdc, 2)
$gfx.ReleaseHdc($hdc)
$gfx.Dispose()

if (-not $okPrint) { Write-Host '  note: PrintWindow returned false, saving anyway' }

$dir = Split-Path -Parent $OutFile
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

Write-Host "  saved  : $OutFile  ($((Get-Item $OutFile).Length) bytes)"

# Close the app politely: send WM_CLOSE so the FormClosing handler runs.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class WinMsg {
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
}
'@
# The "game is running" confirmation only appears if touchHLE is up, which it is
# not here, so WM_CLOSE should close the form directly.
[void][WinMsg]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)

if (-not $proc.WaitForExit(10000)) {
    Write-Host '  window did not close; killing'
    try { $proc.Kill() } catch { }
} else {
    Write-Host "  closed cleanly, exit=$($proc.ExitCode)"
}

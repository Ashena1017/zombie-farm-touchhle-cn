# Verify 游戏管理.exe really starts the manager UI with NO console window.
#
# The complaint this addresses: launching via 游戏管理.bat leaves a black console
# window on screen the whole time the UI is open. A .bat cannot avoid that because
# cmd.exe is a console program. The replacement is compiled with
# /target:winexe (PE subsystem 2), so Windows never allocates a console for it.
#
# The check is empirical: count console windows (class "ConsoleWindowClass")
# before and after launching, and confirm the manager window still appears.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [int]$TimeoutSeconds = 40
)
$root = (Resolve-Path -LiteralPath $Root).Path

$ErrorActionPreference = 'Continue'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class Win {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    public static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }
    public static string Txt(IntPtr h) { var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString(); }

    // All visible top-level windows whose class contains `fragment`.
    public static IntPtr[] VisibleByClass(string fragment) {
        var list = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            if (IsWindowVisible(h) && Cls(h).Contains(fragment)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }

    public static IntPtr FindTopLevel(uint pid, string titlePart) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint wpid; GetWindowThreadProcessId(h, out wpid);
            if (wpid == pid && IsWindowVisible(h) && Txt(h).Contains(titlePart)) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@

function Count-Consoles {
    return ([Win]::VisibleByClass('ConsoleWindowClass')).Count
}

# Locate the launcher by exclusion rather than by its Chinese name: embedding a
# Chinese literal here would risk the BOM/encoding trap this project keeps hitting
# (see _analysis/_ensure_bom.ps1), and the launcher is simply "the other .exe".
$exe = Get-ChildItem -LiteralPath $Root -Filter '*.exe' -File |
    Where-Object { $_.Name -notmatch '^touchHLE' } |
    Sort-Object Length |
    Select-Object -First 1

if (-not $exe) { Write-Host '  FAIL: could not find the launcher executable'; exit 1 }
$exe = $exe.FullName
Write-Host "  launcher: $([System.IO.Path]::GetFileName($exe))  ($((Get-Item -LiteralPath $exe).Length) bytes)"

$before = Count-Consoles
Write-Host "  console windows before : $before"

# Launch the GUI executable without Start-Process, which fails in this session
# when the inherited NO_PROXY variables contain duplicate keys.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $exe
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host "  launched pid=$($proc.Id)"

# Poll for the manager window.
$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    $hwnd = [Win]::FindTopLevel([uint32]$proc.Id, 'Zombie Farm')
    if ($hwnd -eq [IntPtr]::Zero) {
        # The form is created by the child PowerShell, so search by title too.
        foreach ($p in (Get-Process -Name 'powershell' -ErrorAction SilentlyContinue)) {
            if ($p.MainWindowTitle -match 'Zombie Farm') { $hwnd = $p.MainWindowHandle; break }
        }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}

# Give any console a moment to appear if it were going to.
Start-Sleep -Seconds 3

$during = Count-Consoles
$title = ''
if ($hwnd -ne [IntPtr]::Zero) { $title = [Win]::Txt($hwnd) }

Write-Host "  manager window         : '$title'  (hwnd=$hwnd)"
Write-Host "  console windows during : $during"

$ok = $true
if ($hwnd -eq [IntPtr]::Zero) { Write-Host '  FAIL: manager window never appeared' -ForegroundColor Red; $ok = $false }
if ($during -gt $before) {
    Write-Host "  FAIL: $($during - $before) new console window(s) appeared" -ForegroundColor Red
    $ok = $false
} else {
    Write-Host '  => no new console window' -ForegroundColor Green
}

# Confirm the launcher process is a GUI-subsystem binary (2), not console (3).
$bytes = [System.IO.File]::ReadAllBytes($exe)
$pe = [BitConverter]::ToInt32($bytes, 0x3C)
$sub = [BitConverter]::ToUInt16($bytes, $pe + 0x5C)
Write-Host "  PE subsystem           : $sub ($(if ($sub -eq 2) { 'GUI' } else { 'CONSOLE' }))"
if ($sub -ne 2) { $ok = $false }

# Close the UI.
if ($hwnd -ne [IntPtr]::Zero) {
    [void][Win]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
}
if (-not $proc.WaitForExit(15000)) {
    Write-Host '  (launcher still running; killing)'
    try { $proc.Kill() } catch { }
}
Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
    Stop-Process -Force -ErrorAction SilentlyContinue

# Anything left behind?
Start-Sleep -Seconds 2
$after = Count-Consoles
Write-Host "  console windows after  : $after"
if ($after -gt $before) { Write-Host '  WARNING: a console window leaked' -ForegroundColor Yellow }

Write-Host ''
Write-Host ("RESULT: " + $(if ($ok) { 'PASS - no black window, UI appears' } else { 'FAIL' }))
exit $(if ($ok) { 0 } else { 1 })

# Verify the reworked skip-ahead dialog end to end WITHOUT launching the game:
#   1. seed launcher_skip_memory.txt with 6:15
#   2. start the GameManager GUI
#   3. click "start and skip" via BM_CLICK
#   4. find the modal "skip time" dialog and PrintWindow-screenshot it
#   5. close everything politely
# The screenshot proves both the two-box layout AND the memory pre-fill (the
# hours box should read 6, the minutes box 15).
#
# Pure ASCII in code; the one Chinese title is matched by length-agnostic
# substring via Unicode escapes built at runtime (see below).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OutFile = "$root\_analysis\_skip_dialog.png"
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing

# Build the Chinese strings from code points so this file stays pure ASCII.
#   skip-ahead button : 542F 52A8 5E76 8DF3 8FC7 65F6 95F4 2026
#   skip dialog title : 8DF3 8FC7 65F6 95F4
$btnText  = -join (0x542F,0x52A8,0x5E76,0x8DF3,0x8FC7,0x65F6,0x95F4,0x2026 | ForEach-Object { [char]$_ })
$dlgTitle = -join (0x8DF3,0x8FC7,0x65F6,0x95F4 | ForEach-Object { [char]$_ })

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Drawing;
public class SkipCap {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static string TitleOf(IntPtr h) {
        var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString();
    }
    public static IntPtr FindMain(uint wantPid, string needle) {
        IntPtr best = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == wantPid && IsWindowVisible(h) && TitleOf(h).Contains(needle)) best = h;
            return true;
        }, IntPtr.Zero);
        return best;
    }
    public static IntPtr FindTopByTitle(string exact) {
        IntPtr best = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            if (IsWindowVisible(h) && TitleOf(h) == exact) best = h;
            return true;
        }, IntPtr.Zero);
        return best;
    }
    public static IntPtr FindButtonByText(IntPtr parent, string text) {
        // The manager lays buttons inside tab pages / group boxes, so they are
        // not direct children of the form; walk the whole tree recursively.
        // WinForms class names are "WindowsForms10.BUTTON.app.0.xxxx", so match
        // by substring rather than exact "Button".
        IntPtr best = IntPtr.Zero;
        EnumProc walk = null;
        walk = delegate(IntPtr h, IntPtr p) {
            var cls = new StringBuilder(64); GetClassNameW(h, cls, 64);
            if (cls.ToString().IndexOf("BUTTON", StringComparison.OrdinalIgnoreCase) >= 0
                && TitleOf(h) == text) { best = h; return false; }
            EnumChildWindows(h, walk, IntPtr.Zero);
            return best == IntPtr.Zero;
        };
        EnumChildWindows(parent, walk, IntPtr.Zero);
        return best;
    }
}
'@

# 1. seed memory
$memFile = Join-Path $Root 'launcher_skip_memory.txt'
$hadMem = Test-Path -LiteralPath $memFile
$memBackup = $null
if ($hadMem) { $memBackup = [System.IO.File]::ReadAllText($memFile) }
[System.IO.File]::WriteAllText($memFile, '6:15', (New-Object System.Text.UTF8Encoding($false)))
Write-Host "  seeded memory: 6:15"

$proc = $null
try {
    # 2. launch GUI
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' +
        (Join-Path $Root 'GameManager.ps1') + '"'
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    Write-Host "  launched pid=$($proc.Id)"

    # find main window
    $main = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline -and $main -eq [IntPtr]::Zero) {
        $main = [SkipCap]::FindMain([uint32]$proc.Id, 'Zombie Farm')
        if ($main -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
    }
    if ($main -eq [IntPtr]::Zero) { Write-Host '  FAIL: main window not found'; exit 1 }
    Write-Host "  main window: '$([SkipCap]::TitleOf($main))' hwnd=$main"
    Start-Sleep -Seconds 3

    # 3. click the skip button (BM_CLICK = 0x00F5)
    $btn = [SkipCap]::FindButtonByText($main, $btnText)
    if ($btn -eq [IntPtr]::Zero) { Write-Host "  FAIL: button '$btnText' not found"; exit 1 }
    Write-Host "  clicking '$btnText' (hwnd=$btn)"
    # PostMessage (async), NOT SendMessage: the click handler opens a MODAL dialog,
    # so a synchronous SendMessage would block here until the dialog closes and we
    # would never reach the screenshot code below.
    [void][SkipCap]::PostMessage($btn, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

    # 4. find the modal dialog by its exact title
    $dlg = [IntPtr]::Zero
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline -and $dlg -eq [IntPtr]::Zero) {
        $dlg = [SkipCap]::FindTopByTitle($dlgTitle)
        if ($dlg -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 250 }
    }
    if ($dlg -eq [IntPtr]::Zero) { Write-Host "  FAIL: dialog '$dlgTitle' never appeared"; exit 1 }
    Write-Host "  dialog: '$([SkipCap]::TitleOf($dlg))' hwnd=$dlg"
    Start-Sleep -Milliseconds 600

    $r = New-Object SkipCap+RECT
    [void][SkipCap]::GetWindowRect($dlg, [ref]$r)
    $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $gfx.GetHdc()
    [void][SkipCap]::PrintWindow($dlg, $hdc, 2)
    $gfx.ReleaseHdc($hdc); $gfx.Dispose()
    $bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Host "  saved  : $OutFile  ($w x $h)"

    # 5. close dialog (cancel) then the main form (WM_CLOSE = 0x0010)
    [void][SkipCap]::PostMessage($dlg, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 500
    [void][SkipCap]::PostMessage($main, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    if (-not $proc.WaitForExit(10000)) { Write-Host '  main did not exit; killing' }
    else { Write-Host "  closed cleanly, exit=$($proc.ExitCode)" }
} finally {
    if ($proc -and -not $proc.HasExited) { try { $proc.Kill() } catch { } }
    # restore the memory file exactly as it was
    if ($hadMem) { [System.IO.File]::WriteAllText($memFile, $memBackup, (New-Object System.Text.UTF8Encoding($false))) }
    else { Remove-Item -LiteralPath $memFile -Force -ErrorAction SilentlyContinue }
    Write-Host '  memory file restored'
}

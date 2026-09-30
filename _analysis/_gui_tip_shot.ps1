# Open a "?" tip dialog and screenshot it, and also report the body TextBox's
# cursor so the fix can be confirmed without needing to hover by hand.
#
# Pure ASCII (see _analysis/_ensure_bom.ps1 for why).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OutFile = "$root\_analysis\gui_tip.png",
    [int]$TimeoutSeconds = 45
)
$root = (Split-Path -Parent $PSScriptRoot)

$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class TipCap {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static string Text(IntPtr h) { var sb = new StringBuilder(4096); GetWindowTextW(h, sb, 4096); return sb.ToString(); }
    public static string Cls(IntPtr h)  { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }

    public static IntPtr[] TopLevel(uint pid, bool visibleOnly) {
        var list = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint q; GetWindowThreadProcessId(h, out q);
            if (q == pid && (!visibleOnly || IsWindowVisible(h))) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }

    public static IntPtr[] Descendants(IntPtr parent, string fragment) {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Cls(h).Contains(fragment)) { list.Add(h); }
            return true;
        }, IntPtr.Zero);
        return list.ToArray();
    }
}
'@

$manager = Join-Path $Root 'GameManager.ps1'

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' + $manager + '"'
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)

$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    foreach ($w in ([TipCap]::TopLevel([uint32]$proc.Id, $true))) {
        if ([TipCap]::Text($w) -match 'Zombie Farm') { $hwnd = $w; break }
    }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Host 'FAIL: no main window'; exit 1 }
Start-Sleep -Seconds 3

# Press the first "?" button.
$q = @([TipCap]::Descendants($hwnd, 'BUTTON') | Where-Object { [TipCap]::Text($_) -eq '?' })
if ($q.Count -eq 0) { Write-Host 'FAIL: no ? button'; exit 1 }

$before = @([TipCap]::TopLevel([uint32]$proc.Id, $true))
[void][TipCap]::PostMessage($q[0], 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

$dlg = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline -and $dlg -eq [IntPtr]::Zero) {
    foreach ($w in ([TipCap]::TopLevel([uint32]$proc.Id, $true))) {
        if ($before -contains $w) { continue }
        if ([TipCap]::Cls($w) -notlike 'WindowsForms10.Window*') { continue }
        if ([TipCap]::Descendants($w, 'EDIT').Count -gt 0) { $dlg = $w; break }
    }
    if ($dlg -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 300 }
}
if ($dlg -eq [IntPtr]::Zero) { Write-Host 'FAIL: tip dialog did not open'; exit 1 }
Start-Sleep -Seconds 1

Write-Host "dialog: '$([TipCap]::Text($dlg))'"

# Screenshot it.
$r = New-Object TipCap+RECT
[void][TipCap]::GetWindowRect($dlg, [ref]$r)
$w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
[void][TipCap]::PrintWindow($dlg, $dc, 2)
$g.ReleaseHdc($dc); $g.Dispose()
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Host "saved: $OutFile (${w}x${h})"

# Report the text body's properties. WM_GETTEXT already proved the text is there;
# the cursor cannot be queried across processes (GetClassLong on a foreign window
# only yields the class default), so report what the dialog exposes instead.
$edits = [TipCap]::Descendants($dlg, 'EDIT')
Write-Host "edit controls in dialog: $($edits.Count)"
foreach ($e in $edits) {
    $t = [TipCap]::Text($e)
    Write-Host ("  len={0}  first line: {1}" -f $t.Length, ($t -split "`r?`n")[0])
}

[void][TipCap]::PostMessage($dlg, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Seconds 1
[void][TipCap]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Seconds 2
try { $proc.Kill() } catch { }
Get-Process -Name 'powershell' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'Zombie Farm' } |
    Stop-Process -Force -ErrorAction SilentlyContinue

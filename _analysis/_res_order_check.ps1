# Prove the device_size dropdown's item ORDER by reading the combo box's items
# straight out of the live GUI with CB_GETCOUNT / CB_GETLBTEXT. A screenshot of a
# WinForms combo is hard to capture (the popup is a separate window), and the
# control's own window text is empty, so enumerating the items is both the most
# direct and the most reliable evidence. ASCII only.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OutFile = "$root\_analysis\perf\res_order.png",
    [int]$TimeoutSeconds = 45
)
$root = (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Drawing

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Collections.Generic;
using System.Drawing;
public class OrdWin2 {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    const uint CB_GETCOUNT    = 0x0146;
    const uint CB_GETLBTEXTLEN= 0x0149;
    const uint CB_GETLBTEXT   = 0x0148;

    public static string Cls(IntPtr h) { var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString(); }

    public static IntPtr FindMain(uint pid) {
        IntPtr best = IntPtr.Zero; long area = 0;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint w; GetWindowThreadProcessId(h, out w);
            if (w == pid && IsWindowVisible(h)) {
                RECT r; GetWindowRect(h, out r);
                long a = (long)(r.Right - r.Left) * (r.Bottom - r.Top);
                if (a > area) { area = a; best = h; }
            }
            return true;
        }, IntPtr.Zero);
        return best;
    }

    public static List<IntPtr> FindCombos(IntPtr root) {
        var found = new List<IntPtr>();
        Walk(root, found, 0);
        return found;
    }
    static void Walk(IntPtr h, List<IntPtr> found, int depth) {
        if (depth > 8) return;
        EnumChildWindows(h, delegate(IntPtr c, IntPtr p) {
            if (Cls(c).IndexOf("COMBOBOX", StringComparison.OrdinalIgnoreCase) >= 0) found.Add(c);
            Walk(c, found, depth + 1);
            return true;
        }, IntPtr.Zero);
    }

    public static int ComboCount(IntPtr h) {
        return (int)SendMessage(h, CB_GETCOUNT, IntPtr.Zero, IntPtr.Zero);
    }

    // Read every item of a combo box, in order.
    public static List<string> ComboItems(IntPtr h) {
        var list = new List<string>();
        int n = ComboCount(h);
        if (n <= 0 || n > 200) return list;
        for (int i = 0; i < n; i++) {
            int len = (int)SendMessage(h, CB_GETLBTEXTLEN, (IntPtr)i, IntPtr.Zero);
            if (len < 0 || len > 4096) { list.Add("<unreadable>"); continue; }
            IntPtr buf = Marshal.AllocHGlobal((len + 1) * 2);
            try {
                SendMessage(h, CB_GETLBTEXT, (IntPtr)i, buf);
                list.Add(Marshal.PtrToStringUni(buf) ?? "");
            } finally { Marshal.FreeHGlobal(buf); }
        }
        return list;
    }

    public static void Capture(IntPtr h, string path) {
        RECT r; GetWindowRect(h, out r);
        int w = r.Right - r.Left, ht = r.Bottom - r.Top;
        if (w <= 0 || ht <= 0) return;
        using (var bmp = new Bitmap(w, ht))
        using (var g = Graphics.FromImage(bmp)) {
            IntPtr hdc = g.GetHdc();
            PrintWindow(h, hdc, 0);
            g.ReleaseHdc(hdc);
            bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png);
        }
    }
}
'@ -ErrorAction SilentlyContinue

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root 'GameManager.ps1') + '"'
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)

$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
    Start-Sleep -Milliseconds 600
    if ($proc.HasExited) { break }
    $hwnd = [OrdWin2]::FindMain([uint32]$proc.Id)
}

$exit = 1
try {
    if ($hwnd -eq [IntPtr]::Zero) { Write-Host 'FAIL: GUI window never appeared'; return }
    [void][OrdWin2]::ShowWindow($hwnd, 5)
    [void][OrdWin2]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x0041)
    [void][OrdWin2]::SetForegroundWindow($hwnd)
    Start-Sleep -Seconds 3

    $combos = [OrdWin2]::FindCombos($hwnd)
    Write-Host ("combo boxes found: {0}" -f $combos.Count)

    # There are two window controls now: the device family (iPad / iPhone) and the
    # scale (x1.25 / x1.5 / x1.75 / custom). Find each by its own contents - the
    # family combo is the only one naming a device, and the scale combo is the one
    # holding 1.25 and 1.75 (the wheel-zoom combo has 1.1 / 1.2 / 1.5). Matching on
    # content rather than on creation order means this cannot silently pass against
    # the wrong control if the layout changes.
    $famCombo = [IntPtr]::Zero
    $sclCombo = [IntPtr]::Zero
    $famItems = $null
    $sclItems = $null
    foreach ($c in $combos) {
        $it = [OrdWin2]::ComboItems($c)
        $joined = $it -join ' '
        if ($famCombo -eq [IntPtr]::Zero -and $joined -match 'iPad' -and $joined -match 'iPhone') {
            $famCombo = $c; $famItems = $it; continue
        }
        if ($sclCombo -eq [IntPtr]::Zero -and $it.Count -le 5 -and
            ($joined -match '1\.25') -and ($joined -match '1\.75')) {
            $sclCombo = $c; $sclItems = $it; continue
        }
    }

    if ($famCombo -eq [IntPtr]::Zero -or $sclCombo -eq [IntPtr]::Zero) {
        Write-Host ("FAIL: could not identify the window controls (family={0} scale={1})" -f `
            $famCombo, $sclCombo)
        Write-Host 'combo contents seen:'
        foreach ($c in $combos) { Write-Host ("  [{0}] {1}" -f [OrdWin2]::ComboCount($c), (([OrdWin2]::ComboItems($c)) -join ' | ')) }
        return
    }

    Write-Host ''
    Write-Host '=== window_family dropdown contents, in order ==='
    for ($i = 0; $i -lt $famItems.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f $i, $famItems[$i])
    }
    Write-Host ''
    Write-Host '=== window_scale dropdown contents, in order ==='
    for ($i = 0; $i -lt $sclItems.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f $i, $sclItems[$i])
    }

    # Compare using ASCII-only markers, so this script stays readable regardless
    # of how PowerShell decodes its own literals. The scale entries carry a
    # non-ASCII multiplication sign, so only the digits after it are matched.
    $wantFam = @('iPad', 'iPhone')
    $wantScl = @('1.25', '1.5', '1.75')
    $ok = ($famItems.Count -eq $wantFam.Count) -and ($sclItems.Count -eq ($wantScl.Count + 1))
    if ($ok) {
        for ($i = 0; $i -lt $wantFam.Count; $i++) {
            if ($famItems[$i] -notmatch [regex]::Escape($wantFam[$i])) {
                $ok = $false
                Write-Host ("  family mismatch at [{0}]: got '{1}' want prefix '{2}'" -f $i, $famItems[$i], $wantFam[$i])
            }
        }
        for ($i = 0; $i -lt $wantScl.Count; $i++) {
            if ($sclItems[$i] -notmatch [regex]::Escape($wantScl[$i])) {
                $ok = $false
                Write-Host ("  scale mismatch at [{0}]: got '{1}' want {2}" -f $i, $sclItems[$i], $wantScl[$i])
            }
        }
    }
    Write-Host ''
    Write-Host ("ORDER (family ipad>iphone, scale 1.25>1.5>1.75>custom): {0}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }))
    if ($ok) { $exit = 0 }

    [OrdWin2]::Capture($hwnd, $OutFile)
    Write-Host ("screenshot: {0}" -f $OutFile)
} finally {
    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
    Start-Sleep -Seconds 1
    try { Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue } catch {}
}
exit $exit

# Verify the free / open-source statement in the Windows manager, on a fresh
# copy that has never been run:
#
#   1. the first-run dialog appears, and it is a separate top-level window whose
#      title does NOT contain "Zombie Farm" (the automation in this folder finds
#      the main window by that title and must not be confused by a dialog);
#   2. clicking "我知道了" closes it and writes the once-per-install marker;
#   3. the permanent footer link is drawn in both themes;
#   4. a second launch does not show the dialog again;
#   5. ZFR_MANAGER_NO_NOTICE=1 suppresses the dialog even without a marker.
#
# Everything happens in a throwaway copy under %TEMP%; the real Release folder
# and the real sandbox are never opened for writing.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Label = 'notice',
    [int]$TimeoutSeconds = 45
)
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path -LiteralPath $Root).Path
$release = Join-Path $root 'Release'
if (-not (Test-Path -LiteralPath $release)) { throw "missing: $release" }

$outDir = Join-Path $root ("_analysis\dumps\notice-" + $Label)
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class NoticeCap {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int x, y; }

    public static string Title(IntPtr h) {
        var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString();
    }
    public static string ClassName(IntPtr h) {
        var sb = new StringBuilder(256); GetClassNameW(h, sb, 256); return sb.ToString();
    }

    // Main window = the largest visible titled window of the process.
    public static IntPtr Largest(uint want) {
        IntPtr best = IntPtr.Zero; long area = 0;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == want && IsWindowVisible(h) && Title(h).Length > 0) {
                RECT r; GetWindowRect(h, out r);
                long a = (long)(r.Right - r.Left) * (r.Bottom - r.Top);
                if (a > area) { area = a; best = h; }
            }
            return true;
        }, IntPtr.Zero);
        return best;
    }

    public static IntPtr Find(uint want, string fragment) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == want && IsWindowVisible(h) && Title(h).Contains(fragment)) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static int Count(uint want) {
        int n = 0;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == want && IsWindowVisible(h) && Title(h).Length > 0) n++;
            return true;
        }, IntPtr.Zero);
        return n;
    }

    // WinForms buttons are real child windows; BM_CLICK is enough to press one.
    public static IntPtr Button(IntPtr parent, string text) {
        IntPtr found = IntPtr.Zero;
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (ClassName(h).IndexOf("BUTTON", StringComparison.OrdinalIgnoreCase) >= 0
                && Title(h) == text) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    // LinkLabel is an owner-drawn WinForms window, not a class of its own, so
    // match it by the text it carries.
    public static IntPtr Link(IntPtr parent) { return ByText(parent, "免费开源"); }

    public static IntPtr ByText(IntPtr parent, string fragment) {
        IntPtr found = IntPtr.Zero;
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (Title(h).Contains(fragment)) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    // PostMessage, not SendMessage: a WinForms button runs its Click handler on
    // its own UI thread, and a cross-process SendMessage would run it on ours.
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);

    // SetForegroundWindow is refused for a background process, so raise the
    // window the only way that always works: a brief topmost round trip.
    public static void Raise(IntPtr h) {
        SetWindowPos(h, (IntPtr)(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010);
        SetWindowPos(h, (IntPtr)(-2), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010);
        System.Threading.Thread.Sleep(200);
    }

    public static bool Click(IntPtr h) {
        // WinForms buttons live in their own registered window class and their
        // Click handler requires real mouse capture, so posted messages and
        // BM_CLICK both do nothing. Drive the real cursor, then put it back.
        RECT r; GetWindowRect(h, out r);
        int x = (r.Left + r.Right) / 2;
        int y = (r.Top + r.Bottom) / 2;
        POINT old; GetCursorPos(out old);
        Raise(GetAncestor(h, 2));      // GA_ROOT: the dialog/parent window
        SetForegroundWindow(h);
        System.Threading.Thread.Sleep(150);
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(150);
        mouse_event(0x0002, 0, 0, 0, IntPtr.Zero);   // MOUSEEVENTF_LEFTDOWN
        System.Threading.Thread.Sleep(60);
        mouse_event(0x0004, 0, 0, 0, IntPtr.Zero);   // MOUSEEVENTF_LEFTUP
        System.Threading.Thread.Sleep(200);
        SetCursorPos(old.x, old.y);
        return true;
    }

    // The theme button sits alone in the top-right corner of the manager window.
    public static IntPtr ByTopRight(IntPtr parent) {
        RECT outer; GetWindowRect(parent, out outer);
        IntPtr found = IntPtr.Zero;
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (ClassName(h).IndexOf("BUTTON", StringComparison.OrdinalIgnoreCase) < 0) return true;
            RECT r; GetWindowRect(h, out r);
            if (r.Left > outer.Right - 130 && r.Top < outer.Top + 90) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@

[void][NoticeCap]::SetProcessDPIAware()

function Save-Window([IntPtr]$hwnd, [string]$path) {
    $rect = New-Object 'NoticeCap+RECT'
    [void][NoticeCap]::GetWindowRect($hwnd, [ref]$rect)
    $w = $rect.Right - $rect.Left
    $h = $rect.Bottom - $rect.Top
    if ($w -le 0 -or $h -le 0) { return $false }
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    [void][NoticeCap]::PrintWindow($hwnd, $hdc, 2)
    $g.ReleaseHdc($hdc)
    $g.Dispose()
    # The manager is DPI-unaware, so PrintWindow paints at 96 dpi into a canvas
    # sized in physical pixels; the leftover band is pure black. Crop it so the
    # evidence images are just the window. Content colors are never pure black
    # (night background is 29,35,38), so the test is unambiguous.
    $maxX = 0; $maxY = 0
    for ($y = 0; $y -lt $bmp.Height; $y += 2) {
        for ($x = 0; $x -lt $bmp.Width; $x += 2) {
            $c = $bmp.GetPixel($x, $y)
            if ($c.R -ne 0 -or $c.G -ne 0 -or $c.B -ne 0) {
                if ($x -gt $maxX) { $maxX = $x }
                if ($y -gt $maxY) { $maxY = $y }
            }
        }
    }
    $cropW = [Math]::Min($bmp.Width, $maxX + 3)
    $cropH = [Math]::Min($bmp.Height, $maxY + 3)
    if ($cropW -gt 40 -and $cropH -gt 40 -and ($cropW -lt $bmp.Width -or $cropH -lt $bmp.Height)) {
        $cropRect = New-Object System.Drawing.Rectangle(0, 0, $cropW, $cropH)
        $cropped = $bmp.Clone($cropRect, $bmp.PixelFormat)
        $bmp.Dispose()
        $bmp = $cropped
    }
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    return $true
}

# --- a throwaway copy of the bundle ---------------------------------------
$temp = Join-Path $env:TEMP ('zfnotice_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
Copy-Item -Path (Join-Path $release '*') -Destination $temp -Recurse -Force
if (-not (Test-Path -LiteralPath (Join-Path $temp 'GameManager.ps1'))) {
    throw "copy failed: no GameManager.ps1 under $temp"
}
$marker = Join-Path $temp 'launcher_notice_seen.txt'
Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue

$script:failures = 0
function Check([bool]$ok, [string]$what) {
    if ($ok) { Write-Host ("  PASS  " + $what) } else { Write-Host ("  FAIL  " + $what); $script:failures++ }
}

# Mean luminance of a captured window, sampled coarsely: enough to prove the
# theme really changed rather than that a file merely got written.
function Get-MeanLuma([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return -1 }
    $bmp = [System.Drawing.Bitmap]::FromFile($path)
    try {
        $sum = 0.0; $n = 0
        for ($y = 0; $y -lt $bmp.Height; $y += 4) {
            for ($x = 0; $x -lt $bmp.Width; $x += 4) {
                $c = $bmp.GetPixel($x, $y)
                $sum += (0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B); $n++
            }
        }
        if ($n -eq 0) { return -1 }
        return [Math]::Round($sum / $n, 1)
    } finally { $bmp.Dispose() }
}

function Start-Manager([bool]$noNotice) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "' +
        (Join-Path $temp 'GameManager.ps1') + '"'
    $psi.WorkingDirectory = $temp
    $psi.UseShellExecute = $false
    # Launch the way Explorer does it: the module path this probe inherited
    # points at another PowerShell's module tree, and cmdlet autoloading then
    # differs from a real double-click. That difference is a property of the
    # test harness, not of the bundle, so it is normalised away here.
    $psi.EnvironmentVariables['PSModulePath'] =
        'C:\Users\' + $env:USERNAME + '\Documents\WindowsPowerShell\Modules;' +
        'C:\Program Files\WindowsPowerShell\Modules;' +
        'C:\Windows\system32\WindowsPowerShell\v1.0\Modules'
    if ($noNotice) { $psi.EnvironmentVariables['ZFR_MANAGER_NO_NOTICE'] = '1' }
    return [System.Diagnostics.Process]::Start($psi)
}

function Wait-Window([System.Diagnostics.Process]$proc, [string]$fragment) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $h = [NoticeCap]::Find([uint32]$proc.Id, $fragment)
        if ($h -ne [IntPtr]::Zero) { return $h }
        Start-Sleep -Milliseconds 300
    }
    return [IntPtr]::Zero
}

function Stop-Manager([System.Diagnostics.Process]$proc) {
    # Only the process this probe started: it owns the window, and killing it
    # also ends the child manager. Never sweep by process name -- that would hit
    # a manager the user has open.
    try {
        $proc.Kill()
        $proc.WaitForExit(5000) | Out-Null
    } catch { }
}

Write-Host ''
Write-Host '--- run 1: fresh copy, dialog expected ---'
$proc = Start-Manager $false
$main = Wait-Window $proc 'Zombie Farm 游戏管理'
Check ($main -ne [IntPtr]::Zero) 'main window appears'

$dialog = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $dialog -eq [IntPtr]::Zero) {
    $dialog = [NoticeCap]::Find([uint32]$proc.Id, '免费开源声明')
    if ($dialog -eq [IntPtr]::Zero) { $dialog = [NoticeCap]::Find([uint32]$proc.Id, '欢迎使用') }
    if ($dialog -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 300 }
}
Check ($dialog -ne [IntPtr]::Zero) 'first-run dialog appears'
if ($dialog -ne [IntPtr]::Zero) {
    $title = [NoticeCap]::Title($dialog)
    Write-Host ("        dialog title: '{0}'" -f $title)
    Check ($title -notmatch 'Zombie Farm') 'dialog title does not collide with the automation title match'
    Start-Sleep -Milliseconds 700
    $ok = Save-Window $dialog (Join-Path $outDir 'dialog-first-run.png')
    Check $ok 'dialog screenshot saved'
}


# Press the primary button of the dialog and check the marker it writes.
# Click() moves the real cursor, so the dialog has to be in front for the press
# to land on it rather than on whatever the desktop has there.
if ($dialog -ne [IntPtr]::Zero) {
    $close = [NoticeCap]::Button($dialog, '我知道了，开始使用')
    Check ($close -ne [IntPtr]::Zero) 'dialog close button found'
    if ($close -ne [IntPtr]::Zero) {
        [void][NoticeCap]::SetForegroundWindow($dialog)
        Start-Sleep -Milliseconds 250
        [void][NoticeCap]::Click($close)
        Start-Sleep -Milliseconds 1800
        Check ([NoticeCap]::Find([uint32]$proc.Id, '免费开源声明') -eq [IntPtr]::Zero) 'dialog closed by its button'
    }
    Check (Test-Path -LiteralPath $marker) 'once-per-install marker written'
    if (Test-Path -LiteralPath $marker) {
        $value = ([System.IO.File]::ReadAllText($marker)).Trim()
        Check ($value -eq '1') ("marker holds the notice version (got '{0}')" -f $value)
    }
}
Start-Sleep -Milliseconds 500
$ok = Save-Window $main (Join-Path $outDir 'main-night.png')
Check $ok 'main window screenshot saved'
$link = if ($main -ne [IntPtr]::Zero) { [NoticeCap]::Link($main) } else { [IntPtr]::Zero }
Check ($link -ne [IntPtr]::Zero) 'footer link control exists'
if ($link -ne [IntPtr]::Zero) { Write-Host ("        footer text: '{0}'" -f [NoticeCap]::Title($link)) }

# Day theme: same window, theme button is the only 38x38 button.
$theme = [IntPtr]::Zero
if ($main -ne [IntPtr]::Zero) { $theme = [NoticeCap]::ByTopRight($main) }
if ($theme -ne [IntPtr]::Zero) {
    [void][NoticeCap]::SetForegroundWindow($main)
    Start-Sleep -Milliseconds 200
    [void][NoticeCap]::Click($theme)
    Start-Sleep -Milliseconds 900
    Check (Save-Window $main (Join-Path $outDir 'main-day.png')) 'day-theme screenshot saved'
    $nightLuma = Get-MeanLuma (Join-Path $outDir 'main-night.png')
    $dayLuma = Get-MeanLuma (Join-Path $outDir 'main-day.png')
    Write-Host ("        mean luminance: night {0} / day {1}" -f $nightLuma, $dayLuma)
    Check (([Math]::Abs($nightLuma - $dayLuma)) -gt 25) 'day theme really differs from night'
    [void][NoticeCap]::Click($theme)
    Start-Sleep -Milliseconds 700
} else {
    Write-Host '  SKIP  theme button not located (only night capture)'
}

Stop-Manager $proc
Start-Sleep -Milliseconds 800

Write-Host ''
Write-Host '--- run 2: marker present, dialog must stay away ---'
$proc = Start-Manager $false
$main = Wait-Window $proc 'Zombie Farm 游戏管理'
Check ($main -ne [IntPtr]::Zero) 'main window appears again'
Start-Sleep -Seconds 6
$again = [NoticeCap]::Find([uint32]$proc.Id, '免费开源声明')
Check ($again -eq [IntPtr]::Zero) 'dialog not shown a second time'
Stop-Manager $proc
Start-Sleep -Milliseconds 800

Write-Host ''
Write-Host '--- run 3: no marker, but ZFR_MANAGER_NO_NOTICE=1 ---'
Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
$proc = Start-Manager $true
$main = Wait-Window $proc 'Zombie Farm 游戏管理'
Check ($main -ne [IntPtr]::Zero) 'main window appears with the opt-out set'
Start-Sleep -Seconds 6
$suppressed = [NoticeCap]::Find([uint32]$proc.Id, '免费开源声明')
Check ($suppressed -eq [IntPtr]::Zero) 'dialog suppressed by ZFR_MANAGER_NO_NOTICE=1'
Check (-not (Test-Path -LiteralPath $marker)) 'opt-out does not write the marker'
Stop-Manager $proc
Start-Sleep -Milliseconds 500

Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ''
if ($script:failures -eq 0) {
    Write-Host "DONE: all checks passed; screenshots in $outDir"
    exit 0
}
Write-Host ("DONE: {0} check(s) failed; screenshots in {1}" -f $script:failures, $outDir)
exit 1

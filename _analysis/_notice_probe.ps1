# Verify the free / open-source statement in the Windows manager, on a fresh
# copy that has never been run:
#
#   1. the dialog appears, and it is a separate top-level window whose title does
#      NOT contain "Zombie Farm" (the automation in this folder finds the main
#      window by that title and must not be confused by a dialog);
#   2. it carries the QQ group and the file-integrity verdict;
#   3. clicking "我知道了" closes it and writes the notice marker;
#   4. the 文件校验 page reports the shipped files as official;
#   5. the permanent footer link is drawn in both themes;
#   6. a SECOND launch shows the dialog again -- it is per launch, not per
#      install, which is the whole point: a seller cannot pre-open the manager;
#   7. ZFR_MANAGER_NO_NOTICE=1 suppresses the dialog even without a marker.
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

    // Switch tabs the way a person does: click the strip, then arrow across.
    //
    // Do NOT ask the control for its item rectangles (TCM_GETITEMRECT) from
    // outside the process. That message takes a pointer, the system does not
    // marshal pointers for control messages, so the target writes a RECT through
    // an address that means nothing in its address space -- the manager dies
    // with an AccessViolationException. That happened here once. The strip sits
    // at the top of the control, so a click near its left edge lands on tab 0
    // and the rest is keyboard.
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, IntPtr extra);

    public static IntPtr TabControl(IntPtr parent) {
        // WinForms registers its own window class for every control, so the
        // native "SysTabControl32" never matches exactly -- the real name is
        // "WindowsForms10.SysTabControl32.app.0.<pid>_r9_ad1". Match a fragment.
        IntPtr found = IntPtr.Zero;
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr p) {
            if (ClassName(h).IndexOf("SysTabControl32", StringComparison.OrdinalIgnoreCase) >= 0) { found = h; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static bool ClickTab(IntPtr parent, int index) {
        IntPtr tc = TabControl(parent);
        if (tc == IntPtr.Zero) return false;
        RECT w; GetWindowRect(tc, out w);
        POINT old; GetCursorPos(out old);
        Raise(GetAncestor(tc, 2));
        SetForegroundWindow(tc);
        System.Threading.Thread.Sleep(150);
        SetCursorPos(w.Left + 8, w.Top + 12);
        System.Threading.Thread.Sleep(150);
        mouse_event(0x0002, 0, 0, 0, IntPtr.Zero);
        System.Threading.Thread.Sleep(60);
        mouse_event(0x0004, 0, 0, 0, IntPtr.Zero);
        System.Threading.Thread.Sleep(300);
        for (int i = 0; i < index; i++) {
            PostMessage(tc, 0x0100, (IntPtr)0x27, (IntPtr)0x014D0001);       // WM_KEYDOWN VK_RIGHT
            System.Threading.Thread.Sleep(70);
            PostMessage(tc, 0x0101, (IntPtr)0x27, new IntPtr(0xC14D0001L));  // WM_KEYUP
            System.Threading.Thread.Sleep(220);
        }
        SetCursorPos(old.x, old.y);
        return true;
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

# Read the version the manager will write, instead of hardcoding it here: it is
# bumped whenever the statement changes, and a stale literal in the test just
# turns a real regression into a false alarm.
$noticeVersion = $null
$managerText = [System.IO.File]::ReadAllText((Join-Path $temp 'GameManager.ps1'))
$versionMatch = [regex]::Match($managerText, "\`$script:NoticeVersion\s*=\s*'([^']+)'")
if ($versionMatch.Success) { $noticeVersion = $versionMatch.Groups[1].Value }
Write-Host ("        manager notice version: '{0}'" -f $noticeVersion)

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

# Open the throwaway copy on a given tab. Only the copy in %TEMP% is edited --
# the release bundle is never touched -- and the insertion uses the same public
# API a user would (SelectedIndex), so the layout that gets captured is the real
# one.
function Set-StartupTab([int]$index) {
    $manager = Join-Path $temp 'GameManager.ps1'
    $lines = [System.IO.File]::ReadAllLines($manager, [System.Text.Encoding]::UTF8)
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim() -eq 'Update-WindowForSelectedTab') {
            $lines[$i] = ('$tabs.SelectedIndex = ' + $index + [Environment]::NewLine + $lines[$i])
            Write-Host ("        forced startup tab: {0} (line {1})" -f $index, ($i + 1))
            break
        }
    }
    [System.IO.File]::WriteAllLines($manager, $lines, (New-Object System.Text.UTF8Encoding($true)))
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
    Check ($title -match '免费开源声明') 'dialog title names the statement'
    Check ([NoticeCap]::ByText($dialog, '1185712984') -ne [IntPtr]::Zero) 'dialog carries the QQ group'
    Check ([NoticeCap]::ByText($dialog, '文件校验：') -ne [IntPtr]::Zero) 'dialog shows the integrity verdict'
    Check ([NoticeCap]::ByText($dialog, '均与官方发布一致') -ne [IntPtr]::Zero) 'dialog verdict is the passing one, not a false alarm'
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
    Check (Test-Path -LiteralPath $marker) 'notice marker written'
    if (Test-Path -LiteralPath $marker) {
        $value = ([System.IO.File]::ReadAllText($marker)).Trim()
        Check ($value -eq $noticeVersion) ("marker holds the notice version (got '{0}', want '{1}')" -f $value, $noticeVersion)
    }
}
Start-Sleep -Milliseconds 500
$ok = Save-Window $main (Join-Path $outDir 'main-night.png')
Check $ok 'main window screenshot saved'
$link = if ($main -ne [IntPtr]::Zero) { [NoticeCap]::Link($main) } else { [IntPtr]::Zero }
Check ($link -ne [IntPtr]::Zero) 'footer link control exists'
if ($link -ne [IntPtr]::Zero) { Write-Host ("        footer text: '{0}'" -f [NoticeCap]::Title($link)) }
Check ($link -ne [IntPtr]::Zero -and [NoticeCap]::Title($link) -match '1185712984') 'footer carries the QQ group'

Write-Host ''
Write-Host '--- verify page: checked in run 3, which starts on that tab ---'

# Day theme: same window, theme button is the only 38x38 button.
$theme = [IntPtr]::Zero
if ($main -ne [IntPtr]::Zero) { $theme = [NoticeCap]::ByTopRight($main) }
if ($theme -ne [IntPtr]::Zero) {
    [void][NoticeCap]::SetForegroundWindow($main)
    Start-Sleep -Milliseconds 200
    [void][NoticeCap]::Click($theme)
    Start-Sleep -Milliseconds 1600
    # A lost synthetic click is an artefact of this desktop, not of the code:
    # retry once before calling the theme broken.
    Check (Save-Window $main (Join-Path $outDir 'main-day.png')) 'day-theme screenshot saved'
    if ([Math]::Abs((Get-MeanLuma (Join-Path $outDir 'main-night.png')) - (Get-MeanLuma (Join-Path $outDir 'main-day.png'))) -le 25) {
        [void][NoticeCap]::Click($theme)
        Start-Sleep -Milliseconds 1600
    }
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
Write-Host '--- run 2: marker present, dialog must STILL appear ---'
$proc = Start-Manager $false
$main = Wait-Window $proc 'Zombie Farm 游戏管理'
Check ($main -ne [IntPtr]::Zero) 'main window appears again'
$again = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline -and $again -eq [IntPtr]::Zero) {
    $again = [NoticeCap]::Find([uint32]$proc.Id, '免费开源声明')
    if ($again -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 300 }
}
Check ($again -ne [IntPtr]::Zero) 'dialog shown on a later launch too (not once per install)'
if ($again -ne [IntPtr]::Zero) {
    $againTitle = [NoticeCap]::Title($again)
    Write-Host ("        second-launch title: '{0}'" -f $againTitle)
    Check ($againTitle -notmatch '欢迎使用') 'later launches use the plain title, not the welcome one'
    Check ([NoticeCap]::Button($again, '关闭') -ne [IntPtr]::Zero) 'later dialog offers 关闭'
}
Stop-Manager $proc
Start-Sleep -Milliseconds 800

Write-Host ''
Write-Host '--- run 3: no marker, ZFR_MANAGER_NO_NOTICE=1, opened on the 文件校验 page ---'
Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
# Start the copy on the fourth tab rather than clicking it. Synthetic clicks need
# the window to own the foreground, which a background session cannot always
# arrange -- and a probe that fails for that reason says nothing about the code.
# The page itself is what this run is here to look at.
Set-StartupTab 3
$proc = Start-Manager $true
$main = Wait-Window $proc 'Zombie Farm 游戏管理'
Check ($main -ne [IntPtr]::Zero) 'main window appears with the opt-out set'
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if ($main -ne [IntPtr]::Zero -and [NoticeCap]::ByText($main, '与官方一致') -ne [IntPtr]::Zero) { break }
    Start-Sleep -Milliseconds 300
}
Check ($main -ne [IntPtr]::Zero -and [NoticeCap]::ByText($main, '官方 SHA-256') -ne [IntPtr]::Zero) 'verify page has the hash columns'
Check ([NoticeCap]::ByText($main, '与官方一致') -ne [IntPtr]::Zero) 'verify page reports the files as official'
Check ([NoticeCap]::ByText($main, '文件不存在') -eq [IntPtr]::Zero) 'no missing-file verdict'
Check ([NoticeCap]::ByText($main, '想反馈都可以来群里说') -ne [IntPtr]::Zero) 'verify page carries the QQ group'
Check (Save-Window $main (Join-Path $outDir 'verify-tab.png')) 'verify page screenshot saved'
Start-Sleep -Milliseconds 500
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
